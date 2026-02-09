from __future__ import annotations

from collections import defaultdict
from datetime import date
from datetime import timedelta
from typing import Any

from ..models import CourseSpec
from ..models import PlanRow
from ..models import PlanSummary
from ..models import TopicEstimate
from ..models import UserConstraints


class PlanningAgent:
    # Builds a day-by-day study schedule from estimates and constraints."""

    def build_plan(
        self,
        estimates: list[TopicEstimate],
        constraints: UserConstraints,
        course_specs: dict[str, CourseSpec],
    ) -> tuple[list[PlanRow], PlanSummary]:
        start = date.fromisoformat(constraints.start_date)
        exam_dates = self._resolve_exam_dates(course_specs, start)
        end = max(exam_dates.values()) if exam_dates else start + timedelta(days=14)

        base_day_capacity = self._build_day_capacity(start, end, constraints)
        day_capacity = dict(base_day_capacity)
        rows: list[PlanRow] = []

        # Reserve a final-review block before each exam.
        for course_code, exam_day in sorted(exam_dates.items()):
            buffer_day = exam_day - timedelta(days=1)
            if buffer_day < start or buffer_day not in day_capacity:
                continue
            reserve = min(1.0, day_capacity[buffer_day])
            if reserve <= 0:
                continue
            day_capacity[buffer_day] -= reserve
            rows.append(
                PlanRow(
                    date=buffer_day.isoformat(),
                    course_code=course_code,
                    task_type="review",
                    topic_id="final_review",
                    topic_label="Final Review",
                    hours=round(reserve, 2),
                    notes="Reserved pre-exam buffer.",
                )
            )

        topic_capacity_total = round(sum(day_capacity.values()), 2)
        required_by_course = self._required_hours_by_course(estimates)
        target_by_course = self._target_hours_by_course(
            required_by_course=required_by_course,
            exam_dates=exam_dates,
            priority_weights=constraints.priority_weights,
            start=start,
            topic_capacity_total=topic_capacity_total,
        )

        topic_lookup = self._topic_label_lookup(course_specs)
        topic_order = self._topic_order(course_specs)
        remaining = {
            (estimate.course_code, estimate.topic_id): float(estimate.estimated_hours)
            for estimate in estimates
        }
        contact_count = defaultdict(int)
        assigned_topic_hours: dict[str, float] = defaultdict(float)

        current = start
        while current <= end:
            capacity = day_capacity.get(current, 0.0)
            while capacity >= 0.25:
                course_code = self._choose_course(
                    current=current,
                    remaining=remaining,
                    exam_dates=exam_dates,
                    priority_weights=constraints.priority_weights,
                    target_by_course=target_by_course,
                    assigned_topic_hours=assigned_topic_hours,
                    familiarity_by_course=constraints.familiarity_by_course,
                    weakness_by_course=constraints.weakness_by_course,
                )
                if not course_code:
                    break

                topic_id = self._pick_topic(course_code, remaining, topic_order)
                if not topic_id:
                    break

                key = (course_code, topic_id)
                remaining_hours = remaining[key]
                if remaining_hours <= 0:
                    break

                chunk = min(1.5, capacity, remaining_hours)
                task_type = "review" if contact_count[course_code] % 3 == 2 else "study"
                note = "Spaced review block." if task_type == "review" else ""
                rows.append(
                    PlanRow(
                        date=current.isoformat(),
                        course_code=course_code,
                        task_type=task_type,
                        topic_id=topic_id,
                        topic_label=topic_lookup.get((course_code, topic_id), topic_id),
                        hours=round(chunk, 2),
                        notes=note,
                    )
                )
                remaining[key] = round(max(0.0, remaining_hours - chunk), 4)
                capacity = round(capacity - chunk, 4)
                contact_count[course_code] += 1
                assigned_topic_hours[course_code] = round(
                    assigned_topic_hours[course_code] + chunk, 4
                )

            current += timedelta(days=1)

        remaining_total = round(sum(hours for hours in remaining.values() if hours > 0), 2)
        required_total = round(sum(estimate.estimated_hours for estimate in estimates), 2)
        hours_by_course = self._hours_by_course(rows)

        feasible = remaining_total <= 0.5 and required_total <= topic_capacity_total + 0.01
        warnings: list[str] = []
        if not feasible:
            warnings = self._build_infeasible_warnings(
                shortfall=max(remaining_total, round(required_total - topic_capacity_total, 2)),
                required_by_course=required_by_course,
                assigned_topic_hours=assigned_topic_hours,
                planning_days=max(1, len(base_day_capacity)),
            )

        summary = PlanSummary(
            total_hours=round(sum(hours_by_course.values()), 2),
            hours_by_course=dict(sorted(hours_by_course.items())),
            feasible=feasible,
            warnings=warnings,
        )
        return sorted(rows, key=lambda row: (row.date, row.course_code, row.topic_id)), summary

    def _resolve_exam_dates(
        self, course_specs: dict[str, CourseSpec], start: date
    ) -> dict[str, date]:
        resolved: dict[str, date] = {}
        for course_code, spec in course_specs.items():
            if spec.exam_date:
                resolved[course_code] = date.fromisoformat(spec.exam_date)
            else:
                resolved[course_code] = start + timedelta(days=14)
        return resolved

    def _build_day_capacity(
        self, start: date, end: date, constraints: UserConstraints
    ) -> dict[date, float]:
        capacity: dict[date, float] = {}
        current = start
        while current <= end:
            if current.weekday() >= 5:
                capacity[current] = max(0.0, float(constraints.hours_weekend))
            else:
                capacity[current] = max(0.0, float(constraints.hours_weekday))
            current += timedelta(days=1)
        return capacity

    def _choose_course(
        self,
        current: date,
        remaining: dict[tuple[str, str], float],
        exam_dates: dict[str, date],
        priority_weights: dict[str, float],
        target_by_course: dict[str, float],
        assigned_topic_hours: dict[str, float],
        familiarity_by_course: dict[str, float],
        weakness_by_course: dict[str, float],
    ) -> str | None:
        by_course: dict[str, float] = defaultdict(float)
        for (course_code, _topic_id), hours in remaining.items():
            if hours > 0:
                by_course[course_code] += hours

        shortfall_by_course = {
            course_code: max(
                0.0, target_by_course.get(course_code, 0.0) - assigned_topic_hours.get(course_code, 0.0)
            )
            for course_code in by_course
        }
        has_active_shortfall = any(shortfall > 0.01 for shortfall in shortfall_by_course.values())

        best_score = -1.0
        best_course = None
        for course_code, remaining_hours in by_course.items():
            exam_date = exam_dates.get(course_code, current + timedelta(days=14))
            days_left = (exam_date - current).days
            if days_left <= 0:
                continue

            urgency = 1.0 / (days_left + 1.0)
            priority = max(0.25, float(priority_weights.get(course_code, 1.0)))
            familiarity = min(5.0, max(1.0, float(familiarity_by_course.get(course_code, 3.0))))
            weakness = min(5.0, max(1.0, float(weakness_by_course.get(course_code, 3.0))))
            target = max(0.5, target_by_course.get(course_code, remaining_hours))
            remaining_target = shortfall_by_course.get(course_code, 0.0)
            pace_pressure = remaining_target / max(1.0, float(days_left))
            completion_gap = remaining_target / target
            familiarity_boost = max(0.0, 3.0 - familiarity) * 0.12
            weakness_boost = max(0.0, weakness - 3.0) * 0.16

            score = (
                2.8 * pace_pressure
                + 1.4 * completion_gap
                + 1.2 * urgency
                + 0.25 * priority
                + 0.03 * remaining_hours
                + familiarity_boost
                + weakness_boost
            )
            if has_active_shortfall and remaining_target <= 0.01:
                score -= 1.5
            if score > best_score:
                best_score = score
                best_course = course_code
        return best_course

    def _pick_topic(
        self,
        course_code: str,
        remaining: dict[tuple[str, str], float],
        topic_order: dict[str, list[str]],
    ) -> str | None:
        for topic_id in topic_order.get(course_code, []):
            if remaining.get((course_code, topic_id), 0) > 0:
                return topic_id
        return None

    def _topic_order(self, course_specs: dict[str, CourseSpec]) -> dict[str, list[str]]:
        topic_order: dict[str, list[str]] = {}
        for course_code, spec in course_specs.items():
            topic_order[course_code] = [topic.topic_id for topic in spec.topics]
        return topic_order

    def _topic_label_lookup(self, course_specs: dict[str, CourseSpec]) -> dict[tuple[str, str], str]:
        lookup: dict[tuple[str, str], str] = {}
        for course_code, spec in course_specs.items():
            for topic in spec.topics:
                lookup[(course_code, topic.topic_id)] = topic.label
        return lookup

    def _hours_by_course(self, rows: list[PlanRow]) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for row in rows:
            totals[row.course_code] += row.hours
        return {course_code: round(hours, 2) for course_code, hours in totals.items()}

    def _required_hours_by_course(self, estimates: list[TopicEstimate]) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for estimate in estimates:
            totals[estimate.course_code] += float(estimate.estimated_hours)
        return {course_code: round(hours, 2) for course_code, hours in totals.items()}

    def _target_hours_by_course(
        self,
        required_by_course: dict[str, float],
        exam_dates: dict[str, date],
        priority_weights: dict[str, float],
        start: date,
        topic_capacity_total: float,
    ) -> dict[str, float]:
        if not required_by_course:
            return {}

        course_codes = [course_code for course_code, hours in required_by_course.items() if hours > 0]
        if not course_codes:
            return {}

        total_required = sum(required_by_course.values())
        if total_required <= topic_capacity_total + 0.01:
            return dict(required_by_course)

        allocatable = max(0.0, topic_capacity_total)
        targets: dict[str, float] = {course_code: 0.0 for course_code in course_codes}

        min_share = min(3.0, max(0.75, allocatable * 0.12 / max(1, len(course_codes))))
        for course_code in course_codes:
            targets[course_code] = min(required_by_course[course_code], min_share)

        floor_total = sum(targets.values())
        if floor_total > allocatable and floor_total > 0:
            scale = allocatable / floor_total
            for course_code in course_codes:
                targets[course_code] *= scale
            floor_total = sum(targets.values())

        remaining_capacity = max(0.0, allocatable - floor_total)
        weights: dict[str, float] = {}
        for course_code in course_codes:
            days_to_exam = max(
                1, (exam_dates.get(course_code, start + timedelta(days=14)) - start).days
            )
            urgency_factor = 1.0 + 8.0 * (1.0 / (days_to_exam + 1.0))
            demand_factor = max(0.5, required_by_course[course_code]) ** 0.7
            priority_factor = max(0.25, float(priority_weights.get(course_code, 1.0)))
            weights[course_code] = demand_factor * urgency_factor * priority_factor

        for _ in range(6):
            if remaining_capacity <= 0.01:
                break

            room = {
                course_code: max(0.0, required_by_course[course_code] - targets[course_code])
                for course_code in course_codes
            }
            weighted_room_total = sum(
                weights[course_code] * room[course_code]
                for course_code in course_codes
                if room[course_code] > 0
            )
            if weighted_room_total <= 0:
                break

            added = 0.0
            for course_code in course_codes:
                if room[course_code] <= 0:
                    continue
                proportional = (
                    remaining_capacity
                    * (weights[course_code] * room[course_code])
                    / weighted_room_total
                )
                increment = min(room[course_code], proportional)
                targets[course_code] += increment
                added += increment
            if added <= 1e-6:
                break
            remaining_capacity = max(0.0, remaining_capacity - added)

        return {course_code: round(hours, 2) for course_code, hours in targets.items()}

    def _build_infeasible_warnings(
        self,
        shortfall: float,
        required_by_course: dict[str, float],
        assigned_topic_hours: dict[str, float],
        planning_days: int,
    ) -> list[str]:
        effective_shortfall = max(0.0, shortfall)
        extra_per_day = effective_shortfall / max(1, planning_days)

        uncovered = []
        for course_code, required_hours in required_by_course.items():
            assigned = assigned_topic_hours.get(course_code, 0.0)
            gap = max(0.0, required_hours - assigned)
            uncovered.append((course_code, gap))
        uncovered.sort(key=lambda item: item[1], reverse=True)
        top_gaps = [item for item in uncovered if item[1] > 0.01][:2]
        if top_gaps:
            gap_text = ", ".join(f"{course} ({gap:.1f}h)" for course, gap in top_gaps)
        else:
            gap_text = "none"

        return [
            (
                f"Current scope exceeds available study time by about {effective_shortfall:.1f} hours; "
                f"add roughly {extra_per_day:.1f} hours/day to fully cover all topics."
            ),
            f"Largest uncovered load: {gap_text}. Prioritize these first in your next iteration.",
            (
                "If time cannot increase, trim low-priority chapters and use a compressed mix: "
                "60% practice, 25% review, 15% reading."
            ),
        ]
