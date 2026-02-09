from __future__ import annotations

from datetime import date
from typing import Any

from ..models import CourseSpec
from ..models import UserConstraints


class HITLAgent:
    """Validates extracted assumptions and applies user overrides."""

    def default_constraints(self) -> UserConstraints:
        return UserConstraints(
            start_date=date.today().isoformat(),
            hours_weekday=3.0,
            hours_weekend=6.0,
            priority_weights={},
            familiarity_by_course={},
            coverage_by_course={},
            weakness_by_course={},
            notes="",
        )

    def set_constraints(
        self,
        constraints: UserConstraints | dict[str, Any] | None,
        existing: UserConstraints | None = None,
    ) -> UserConstraints:
        base = existing or self.default_constraints()
        if constraints is None:
            return base
        incoming = (
            constraints
            if isinstance(constraints, UserConstraints)
            else UserConstraints.model_validate(constraints)
        )
        merged = base.model_copy(deep=True)
        merged.start_date = incoming.start_date or merged.start_date
        merged.hours_weekday = incoming.hours_weekday
        merged.hours_weekend = incoming.hours_weekend
        merged.priority_weights = incoming.priority_weights or merged.priority_weights
        merged.familiarity_by_course = (
            incoming.familiarity_by_course or merged.familiarity_by_course
        )
        merged.coverage_by_course = incoming.coverage_by_course or merged.coverage_by_course
        merged.weakness_by_course = incoming.weakness_by_course or merged.weakness_by_course
        merged.notes = incoming.notes or merged.notes
        merged.timezone = incoming.timezone or merged.timezone
        return merged

    def apply_overrides(
        self,
        constraints: UserConstraints,
        overrides: dict[str, Any] | None = None,
        note: str = "",
    ) -> UserConstraints:
        if not overrides:
            return constraints.model_copy(deep=True)

        updated = constraints.model_copy(deep=True)
        for key, value in overrides.items():
            if key in {
                "priority_weights",
                "familiarity_by_course",
                "coverage_by_course",
                "weakness_by_course",
            } and isinstance(value, dict):
                source = {str(k).upper(): float(v) for k, v in value.items()}
                if key == "priority_weights":
                    merged = dict(updated.priority_weights)
                    merged.update(source)
                    updated.priority_weights = merged
                elif key == "familiarity_by_course":
                    merged = dict(updated.familiarity_by_course)
                    merged.update(source)
                    updated.familiarity_by_course = merged
                elif key == "coverage_by_course":
                    merged = dict(updated.coverage_by_course)
                    merged.update(source)
                    updated.coverage_by_course = merged
                elif key == "weakness_by_course":
                    merged = dict(updated.weakness_by_course)
                    merged.update(source)
                    updated.weakness_by_course = merged
            elif hasattr(updated, key):
                setattr(updated, key, value)
        if note:
            updated.notes = (updated.notes + " | " + note).strip(" |")
        try:
            return UserConstraints.model_validate(updated.model_dump())
        except Exception as exc:  # pragma: no cover - defensive conversion branch
            raise ValueError("Invalid HITL overrides payload.") from exc

    def review_course_specs(self, course_specs: dict[str, CourseSpec]) -> list[str]:
        """Returns confirmation prompts for ambiguous extracted data."""
        prompts: list[str] = []
        for course_code, spec in sorted(course_specs.items()):
            if not spec.exam_date:
                prompts.append(
                    f"{course_code}: exam date missing; please confirm date before planning."
                )
            if not spec.topics:
                prompts.append(
                    f"{course_code}: topics missing; please confirm chapter coverage."
                )
            if spec.confidence == "low":
                prompts.append(
                    f"{course_code}: low-confidence extraction; please verify scope."
                )
        return prompts

    def build_intake_questions(self, course_codes: list[str]) -> list[str]:
        ordered = ", ".join(sorted(course_codes)) if course_codes else "SYSD300, PHYS234, HLTH204"
        return [
            (
                "HITL Q1 - Rank exam priority as a JSON array from highest to lowest, "
                f"using course codes [{ordered}]. Example: [\"PHYS234\",\"SYSD300\",\"HLTH204\"]."
            ),
            (
                "HITL Q2 - Familiarity per course (1-5, where 1=not comfortable, 5=very comfortable). "
                "Provide JSON object. Example: {\"PHYS234\":2,\"SYSD300\":3,\"HLTH204\":4}."
            ),
            (
                "HITL Q3 - Coverage completed per course in percentage (0-100). "
                "Provide JSON object. Example: {\"PHYS234\":25,\"SYSD300\":50,\"HLTH204\":60}."
            ),
            (
                "HITL Q4 - Weakness level per course (1-5, where 5=weakest). "
                "Provide JSON object. Example: {\"PHYS234\":5,\"SYSD300\":3,\"HLTH204\":2}."
            ),
            (
                "HITL Q5 - Optional time update as JSON object, e.g. "
                "{\"hours_weekday\":4,\"hours_weekend\":7}."
            ),
        ]

    def apply_intake_answers(
        self,
        constraints: UserConstraints,
        answers: dict[str, Any],
        course_codes: list[str],
    ) -> tuple[UserConstraints, list[str]]:
        updated = constraints.model_copy(deep=True)
        notes: list[str] = []

        ranked_courses = [
            str(code).upper()
            for code in answers.get("ranked_courses", [])
            if str(code).strip()
        ]
        if ranked_courses:
            ranked_courses = [code for code in ranked_courses if code in set(course_codes)]

        familiarity = self._float_map(answers.get("familiarity_by_course"))
        coverage = self._float_map(answers.get("coverage_by_course"))
        weakness = self._float_map(answers.get("weakness_by_course"))
        hours_update = answers.get("hours")

        if familiarity:
            updated.familiarity_by_course.update(
                {k: min(5.0, max(1.0, v)) for k, v in familiarity.items()}
            )
        if coverage:
            updated.coverage_by_course.update(
                {k: min(100.0, max(0.0, v)) for k, v in coverage.items()}
            )
        if weakness:
            updated.weakness_by_course.update(
                {k: min(5.0, max(1.0, v)) for k, v in weakness.items()}
            )

        if isinstance(hours_update, dict):
            if "hours_weekday" in hours_update:
                updated.hours_weekday = max(0.0, float(hours_update["hours_weekday"]))
            if "hours_weekend" in hours_update:
                updated.hours_weekend = max(0.0, float(hours_update["hours_weekend"]))

        derived_priority: dict[str, float] = {}
        known_codes = sorted(set(course_codes))
        for index, course_code in enumerate(ranked_courses):
            derived_priority[course_code] = derived_priority.get(course_code, 1.0) + max(
                0.0, 0.35 - (index * 0.1)
            )

        for course_code in known_codes:
            familiarity_score = updated.familiarity_by_course.get(course_code, 3.0)
            weakness_score = updated.weakness_by_course.get(course_code, 3.0)
            coverage_score = updated.coverage_by_course.get(course_code, 0.0)

            familiarity_boost = max(0.0, 3.0 - familiarity_score) * 0.08
            weakness_boost = max(0.0, weakness_score - 3.0) * 0.12
            coverage_penalty = min(0.4, max(0.0, coverage_score / 100.0) * 0.4)

            derived = 1.0 + familiarity_boost + weakness_boost - coverage_penalty
            if course_code in derived_priority:
                derived += derived_priority[course_code] - 1.0
            existing = updated.priority_weights.get(course_code, 1.0)
            blended = (0.4 * existing) + (0.6 * derived)
            updated.priority_weights[course_code] = round(min(1.9, max(0.55, blended)), 2)

        notes.append(
            "Applied HITL profile (ranking, familiarity, coverage, weakness) to course priorities."
        )
        if isinstance(hours_update, dict):
            notes.append(
                f"Updated study time to weekday={updated.hours_weekday:.1f}, "
                f"weekend={updated.hours_weekend:.1f}."
            )

        return updated, notes

    @staticmethod
    def _float_map(value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        output: dict[str, float] = {}
        for key, raw in value.items():
            try:
                output[str(key).upper()] = float(raw)
            except (TypeError, ValueError):
                continue
        return output
