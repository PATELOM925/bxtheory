from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from google.adk.tools.tool_context import ToolContext
from google.genai import types as genai_types

from ..models import CourseSpec
from ..models import FileRef
from ..models import PlanRow
from ..models import PlanSummary
from ..models import TopicEstimate
from ..models import UserConstraints
from .estimation import EstimatorAgent
from .formatting import FormattingAgent
from .hitl import HITLAgent
from .ingestion import IngestionAgent
from .planning import PlanningAgent


KEY_FILES = "files_by_sha"
KEY_COURSE_SPECS = "course_specs"
KEY_CONSTRAINTS = "constraints"
KEY_ESTIMATES = "topic_estimates"
KEY_PLAN_ROWS = "plan_rows"
KEY_PLAN_SUMMARY = "plan_summary"
KEY_HITL_HISTORY = "hitl_history"
KEY_HITL_PROFILE = "hitl_profile"
HITL_HISTORY_MAX = 10


class OrchestratorEngine:
    """Coordinates ingestion, HITL, estimation, planning and formatting steps."""

    def __init__(self, module_dir: str) -> None:
        self._module_dir = module_dir
        self.ingestion_agent = IngestionAgent()
        self.hitl_agent = HITLAgent()
        self.estimator_agent = EstimatorAgent()
        self.planning_agent = PlanningAgent()
        self.formatting_agent = FormattingAgent()

    # ----- Tool contract methods -----
    def register_files(self, file_paths: list[str], tool_context: ToolContext) -> dict[str, Any]:
        files_by_sha = self._state_files(tool_context)
        registered, updated = self.ingestion_agent.register_files(file_paths, files_by_sha)
        tool_context.state[KEY_FILES] = updated
        warnings: list[str] = []

        missing_paths = []
        for file_path in file_paths:
            if not Path(file_path).expanduser().resolve().exists():
                missing_paths.append(file_path)
        if missing_paths:
            warnings.append(
                "Some file paths were not found and were skipped: " + ", ".join(missing_paths)
            )

        unknown_kind_files = [file_ref.filename for file_ref in registered if file_ref.kind == "unknown"]
        if unknown_kind_files:
            warnings.append(
                "Unrecognized file type for: "
                + ", ".join(sorted(unknown_kind_files))
                + ". Use filenames containing 'midterm overview', 'syllabus', or 'textbook'."
            )

        self._append_hitl_history(tool_context, warnings)
        return {
            "registered_count": len(registered),
            "registered_files": [file_ref.model_dump() for file_ref in registered],
            "warnings": warnings,
        }

    def extract_course_specs(
        self,
        files_json: str = "",
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        files_by_sha = self._state_files(tool_context)
        if files_json.strip():
            files_payload = self._parse_json_list(files_json, field_name="files_json")
            validated_files = [FileRef.model_validate(file_item) for file_item in files_payload]
            files_by_sha = {file_ref.sha256: file_ref.model_dump() for file_ref in validated_files}
            tool_context.state[KEY_FILES] = files_by_sha

        start_date = self._state_constraints(tool_context).start_date
        course_specs, warnings = self.ingestion_agent.extract_course_specs_with_warnings(
            files_by_sha=files_by_sha,
            start_date=start_date,
        )
        tool_context.state[KEY_COURSE_SPECS] = {
            code: spec.model_dump() for code, spec in course_specs.items()
        }

        prompts = self.hitl_agent.review_course_specs(course_specs)
        intake_questions = self.hitl_agent.build_intake_questions(
            sorted(course_specs.keys())
        )
        prompts.extend(intake_questions)
        if not course_specs:
            prompts.append("No available course sources. Please register valid course documents.")

        self._append_hitl_history(tool_context, warnings + prompts)

        return {
            "course_specs": {code: spec.model_dump() for code, spec in course_specs.items()},
            "hitl_prompts": prompts,
            "hitl_questions": intake_questions,
            "warnings": warnings,
        }

    def get_hitl_questions(self, tool_context: ToolContext | None = None) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        course_codes = sorted(self._state_course_specs(tool_context).keys())
        questions = self.hitl_agent.build_intake_questions(course_codes)
        return {
            "course_codes": course_codes,
            "hitl_questions": questions,
            "answer_schema_example": {
                "ranked_courses": ["PHYS234", "SYSD300", "HLTH204"],
                "familiarity_by_course": {"PHYS234": 2, "SYSD300": 3, "HLTH204": 4},
                "coverage_by_course": {"PHYS234": 20, "SYSD300": 35, "HLTH204": 55},
                "weakness_by_course": {"PHYS234": 5, "SYSD300": 3, "HLTH204": 2},
                "hours": {"hours_weekday": 4, "hours_weekend": 7},
            },
        }

    def apply_hitl_profile(
        self,
        answers_json: str,
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        answers = self._parse_json_dict(answers_json, field_name="answers_json")
        course_codes = sorted(self._state_course_specs(tool_context).keys())
        updated, notes = self.hitl_agent.apply_intake_answers(
            constraints=self._state_constraints(tool_context),
            answers=answers,
            course_codes=course_codes,
        )

        tool_context.state[KEY_CONSTRAINTS] = updated.model_dump()
        tool_context.state[KEY_HITL_PROFILE] = answers
        self._append_hitl_history(tool_context, notes)
        return {
            "constraints": updated.model_dump(),
            "notes": notes,
        }

    def set_constraints(
        self,
        constraints_json: str = "",
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        constraints = (
            self._parse_json_dict(constraints_json, field_name="constraints_json")
            if constraints_json.strip()
            else None
        )
        merged = self.hitl_agent.set_constraints(
            constraints=constraints,
            existing=self._state_constraints(tool_context),
        )
        tool_context.state[KEY_CONSTRAINTS] = merged.model_dump()
        return {"constraints": merged.model_dump()}

    def apply_hitl_edits(
        self,
        overrides_json: str = "",
        note: str = "",
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        overrides = (
            self._parse_json_dict(overrides_json, field_name="overrides_json")
            if overrides_json.strip()
            else None
        )
        updated = self.hitl_agent.apply_overrides(
            constraints=self._state_constraints(tool_context),
            overrides=overrides,
            note=note,
        )
        tool_context.state[KEY_CONSTRAINTS] = updated.model_dump()
        if note:
            self._append_hitl_history(tool_context, [note])
        return {"constraints": updated.model_dump()}

    def estimate_topic_hours(
        self,
        course_specs_json: str = "",
        constraints_json: str = "",
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        if course_specs_json.strip():
            course_specs = self._parse_json_dict(
                course_specs_json, field_name="course_specs_json"
            )
            resolved_specs = {
                str(course_code): CourseSpec.model_validate(spec)
                for course_code, spec in course_specs.items()
            }
        else:
            resolved_specs = self._state_course_specs(tool_context)

        if not resolved_specs:
            tool_context.state[KEY_ESTIMATES] = []
            return {
                "topic_estimates": [],
                "warnings": [
                    "No course specs available. Register files and run extract_course_specs first."
                ],
            }

        constraints = (
            self._parse_json_dict(constraints_json, field_name="constraints_json")
            if constraints_json.strip()
            else None
        )
        resolved_constraints = self.hitl_agent.set_constraints(
            constraints=constraints,
            existing=self._state_constraints(tool_context),
        )
        estimates = self.estimator_agent.estimate_topic_hours(
            course_specs=resolved_specs,
            constraints=resolved_constraints,
            files_by_sha=self._state_files(tool_context),
        )
        tool_context.state[KEY_ESTIMATES] = [estimate.model_dump() for estimate in estimates]
        return {"topic_estimates": [estimate.model_dump() for estimate in estimates]}

    def build_plan(
        self,
        estimates_json: str = "",
        constraints_json: str = "",
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        if estimates_json.strip():
            estimates = self._parse_json_list(estimates_json, field_name="estimates_json")
            resolved_estimates = [TopicEstimate.model_validate(estimate) for estimate in estimates]
        else:
            resolved_estimates = self._state_estimates(tool_context)

        if not resolved_estimates:
            summary = PlanSummary(
                total_hours=0.0,
                hours_by_course={},
                feasible=False,
                warnings=[
                    "No topic estimates available. Run estimate_topic_hours after file extraction."
                ],
            )
            tool_context.state[KEY_PLAN_ROWS] = []
            tool_context.state[KEY_PLAN_SUMMARY] = summary.model_dump()
            return {
                "plan_rows": [],
                "plan_summary": summary.model_dump(),
            }

        constraints = (
            self._parse_json_dict(constraints_json, field_name="constraints_json")
            if constraints_json.strip()
            else None
        )
        resolved_constraints = self.hitl_agent.set_constraints(
            constraints=constraints,
            existing=self._state_constraints(tool_context),
        )
        plan_rows, summary = self.planning_agent.build_plan(
            estimates=resolved_estimates,
            constraints=resolved_constraints,
            course_specs=self._state_course_specs(tool_context),
        )
        tool_context.state[KEY_PLAN_ROWS] = [row.model_dump() for row in plan_rows]
        tool_context.state[KEY_PLAN_SUMMARY] = summary.model_dump()
        return {
            "plan_rows": [row.model_dump() for row in plan_rows],
            "plan_summary": summary.model_dump(),
        }

    async def export_plan(
        self,
        plan_rows_json: str = "",
        summary_json: str = "",
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        if plan_rows_json.strip():
            plan_rows = self._parse_json_list(plan_rows_json, field_name="plan_rows_json")
            resolved_rows = [PlanRow.model_validate(row) for row in plan_rows]
        else:
            resolved_rows = self._state_plan_rows(tool_context)

        if summary_json.strip():
            summary = self._parse_json_dict(summary_json, field_name="summary_json")
            resolved_summary = PlanSummary.model_validate(summary)
        else:
            resolved_summary = self._state_plan_summary(tool_context)
        output_dir = self.formatting_agent.default_output_dir(self._module_dir)
        exported = self.formatting_agent.export_plan(
            plan_rows=resolved_rows,
            summary=resolved_summary,
            output_dir=output_dir,
        )
        artifact_versions = await self._publish_artifacts(tool_context=tool_context, exported=exported)
        return {
            "artifacts": exported,
            "artifact_versions": artifact_versions,
            "plan_summary": resolved_summary.model_dump(),
        }

    async def run_study_planner(
        self,
        file_paths: list[str],
        constraints_json: str = "",
        hitl_answers_json: str = "",
        hitl_overrides_json: str = "",
        hitl_note: str = "",
        require_hitl_profile: bool = False,
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        if tool_context is None:
            raise ValueError("tool_context is required")

        registration = self.register_files(file_paths=file_paths, tool_context=tool_context)
        if not self._state_files(tool_context):
            warnings = list(registration.get("warnings", []))
            warnings.append("No files were registered. Confirm file paths and try again.")
            return {
                "message": "No available files in session. Please register valid source files first.",
                "warnings": warnings,
            }

        extracted = self.extract_course_specs(tool_context=tool_context)
        if not extracted.get("course_specs"):
            return {
                "message": "No available course sources after parsing. Please register valid course files.",
                "warnings": extracted.get("warnings", []),
                "hitl_questions": extracted.get("hitl_questions", []),
            }

        self.set_constraints(constraints_json=constraints_json, tool_context=tool_context)
        if hitl_answers_json.strip():
            self.apply_hitl_profile(
                answers_json=hitl_answers_json,
                tool_context=tool_context,
            )
        elif require_hitl_profile and not self._has_hitl_profile(self._state_constraints(tool_context)):
            return {
                "message": "HITL profile is required before planning. Please answer the HITL questions.",
                "hitl_questions": extracted.get("hitl_questions", []),
                "constraints": self._state_constraints(tool_context).model_dump(),
            }

        if hitl_overrides_json.strip() or hitl_note:
            self.apply_hitl_edits(
                overrides_json=hitl_overrides_json,
                note=hitl_note,
                tool_context=tool_context,
            )
        self.estimate_topic_hours(tool_context=tool_context)
        self.build_plan(tool_context=tool_context)
        exported = await self.export_plan(tool_context=tool_context)
        return {
            "message": "Study plan generated successfully.",
            "artifacts": exported["artifacts"],
            "artifact_versions": exported.get("artifact_versions", {}),
            "plan_summary": self._state_plan_summary(tool_context).model_dump(),
        }

    def get_state_snapshot(self, tool_context: ToolContext) -> dict[str, Any]:
        return {
            KEY_FILES: self._state_files(tool_context),
            KEY_COURSE_SPECS: {
                code: spec.model_dump()
                for code, spec in self._state_course_specs(tool_context).items()
            },
            KEY_CONSTRAINTS: self._state_constraints(tool_context).model_dump(),
            KEY_ESTIMATES: [estimate.model_dump() for estimate in self._state_estimates(tool_context)],
            KEY_PLAN_ROWS: [row.model_dump() for row in self._state_plan_rows(tool_context)],
            KEY_PLAN_SUMMARY: self._state_plan_summary(tool_context).model_dump(),
            KEY_HITL_HISTORY: self._state_hitl_history(tool_context),
            KEY_HITL_PROFILE: dict(tool_context.state.get(KEY_HITL_PROFILE, {})),
        }

    # ----- State helpers -----
    def _state_files(self, tool_context: ToolContext) -> dict[str, dict[str, Any]]:
        return dict(tool_context.state.get(KEY_FILES, {}))

    def _state_course_specs(self, tool_context: ToolContext) -> dict[str, CourseSpec]:
        payload = tool_context.state.get(KEY_COURSE_SPECS, {})
        return {
            str(course_code): CourseSpec.model_validate(spec)
            for course_code, spec in payload.items()
        }

    def _state_constraints(self, tool_context: ToolContext) -> UserConstraints:
        payload = tool_context.state.get(KEY_CONSTRAINTS)
        if payload:
            return UserConstraints.model_validate(payload)
        defaults = self.hitl_agent.default_constraints()
        tool_context.state[KEY_CONSTRAINTS] = defaults.model_dump()
        return defaults

    def _state_estimates(self, tool_context: ToolContext) -> list[TopicEstimate]:
        payload = tool_context.state.get(KEY_ESTIMATES, [])
        return [TopicEstimate.model_validate(item) for item in payload]

    def _state_plan_rows(self, tool_context: ToolContext) -> list[PlanRow]:
        payload = tool_context.state.get(KEY_PLAN_ROWS, [])
        return [PlanRow.model_validate(item) for item in payload]

    def _state_plan_summary(self, tool_context: ToolContext) -> PlanSummary:
        payload = tool_context.state.get(KEY_PLAN_SUMMARY)
        if payload:
            return PlanSummary.model_validate(payload)
        return PlanSummary(total_hours=0.0, hours_by_course={}, feasible=False, warnings=[])

    def _state_hitl_history(self, tool_context: ToolContext) -> list[str]:
        return list(tool_context.state.get(KEY_HITL_HISTORY, []))

    @staticmethod
    def _has_hitl_profile(constraints: UserConstraints) -> bool:
        return bool(
            constraints.familiarity_by_course
            or constraints.coverage_by_course
            or constraints.weakness_by_course
        )

    def _append_hitl_history(self, tool_context: ToolContext, items: list[str]) -> None:
        if not items:
            return
        normalized = [item.strip() for item in items if item and item.strip()]
        if not normalized:
            return
        history = self._state_hitl_history(tool_context)
        history.extend(normalized)
        tool_context.state[KEY_HITL_HISTORY] = history[-HITL_HISTORY_MAX:]

    async def _publish_artifacts(
        self, tool_context: ToolContext, exported: dict[str, str]
    ) -> dict[str, int]:
        save_artifact = getattr(tool_context, "save_artifact", None)
        if not callable(save_artifact):
            return {}

        specs = (
            ("study_plan.csv", exported.get("csv_path", ""), "text/csv"),
            ("study_plan.md", exported.get("md_path", ""), "text/markdown"),
        )
        versions: dict[str, int] = {}
        for filename, local_path, mime_type in specs:
            if not local_path:
                continue
            path = Path(local_path)
            if not path.exists():
                continue

            payload = genai_types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)
            result = save_artifact(
                filename=filename,
                artifact=payload,
                custom_metadata={"local_path": str(path)},
            )
            if inspect.isawaitable(result):
                result = await result

            if isinstance(result, int):
                versions[filename] = result

        return versions

    @staticmethod
    def _parse_json_dict(payload: str, field_name: str) -> dict[str, Any]:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must be a JSON object.")
        return parsed

    @staticmethod
    def _parse_json_list(payload: str, field_name: str) -> list[Any]:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON.") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{field_name} must be a JSON array.")
        return parsed
