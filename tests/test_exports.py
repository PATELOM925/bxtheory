from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from multi_tool_agent.agents.orchestrator import OrchestratorEngine
from multi_tool_agent.models import PlanRow
from multi_tool_agent.models import PlanSummary
from multi_tool_agent.tools.export import CSV_HEADERS
from multi_tool_agent.tools.export import export_plan


def test_export_plan_contract_and_markdown_order(tmp_path: Path) -> None:
    rows = [
        PlanRow(
            date="2026-02-10",
            course_code="SYSD300",
            task_type="study",
            topic_id="ch1",
            topic_label="Chapter 1",
            hours=1.5,
            notes="",
        ),
        PlanRow(
            date="2026-02-11",
            course_code="SYSD300",
            task_type="review",
            topic_id="ch1",
            topic_label="Chapter 1",
            hours=0.5,
            notes="Spaced review block.",
        ),
    ]
    summary = PlanSummary(
        total_hours=2.0,
        hours_by_course={"SYSD300": 2.0},
        feasible=True,
        warnings=[],
    )

    exported = export_plan(rows, summary, str(tmp_path))
    csv_path = Path(exported["csv_path"])
    md_path = Path(exported["md_path"])
    assert csv_path.exists()
    assert md_path.exists()

    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == ",".join(CSV_HEADERS)

    markdown = md_path.read_text(encoding="utf-8")
    summary_index = markdown.index("## Summary")
    plan_index = markdown.index("## Day-by-Day Plan")
    assert summary_index < plan_index


@dataclass
class DummyArtifactContext:
    state: dict

    def __post_init__(self) -> None:
        self.saved_artifacts: list[str] = []

    async def save_artifact(self, filename, artifact, custom_metadata=None) -> int:
        self.saved_artifacts.append(filename)
        return len(self.saved_artifacts)


def test_orchestrator_export_publishes_artifacts(tmp_path: Path) -> None:
    ctx = DummyArtifactContext(state={})
    engine = OrchestratorEngine(module_dir=str(tmp_path))
    rows = [
        PlanRow(
            date="2026-02-10",
            course_code="PHYS234",
            task_type="study",
            topic_id="ch1",
            topic_label="Chapter 1",
            hours=2.0,
            notes="",
        )
    ]
    summary = PlanSummary(
        total_hours=2.0,
        hours_by_course={"PHYS234": 2.0},
        feasible=True,
        warnings=[],
    )

    result = asyncio.run(
        engine.export_plan(
            plan_rows_json=json.dumps([row.model_dump() for row in rows]),
            summary_json=json.dumps(summary.model_dump()),
            tool_context=ctx,  # type: ignore[arg-type]
        )
    )

    assert Path(result["artifacts"]["csv_path"]).exists()
    assert Path(result["artifacts"]["md_path"]).exists()
    assert set(ctx.saved_artifacts) == {"study_plan.csv", "study_plan.md"}
    assert set(result["artifact_versions"]) == {"study_plan.csv", "study_plan.md"}
