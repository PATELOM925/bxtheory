from __future__ import annotations

from collections import defaultdict

from multi_tool_agent.agents.planning import PlanningAgent
from multi_tool_agent.models import CourseSpec
from multi_tool_agent.models import TopicEstimate
from multi_tool_agent.models import TopicSpec
from multi_tool_agent.models import UserConstraints


def test_planner_infeasible_returns_exactly_three_options() -> None:
    planner = PlanningAgent()
    course_specs = {
        "PHYS234": CourseSpec(
            course_code="PHYS234",
            exam_date="2026-02-12",
            topics=[
                TopicSpec(topic_id="ch1", label="Chapter 1", chapter_start=1, chapter_end=1),
                TopicSpec(topic_id="ch2", label="Chapter 2", chapter_start=2, chapter_end=2),
            ],
            source_files=[],
            confidence="high",
        )
    }
    estimates = [
        TopicEstimate(
            course_code="PHYS234",
            topic_id="ch1",
            estimated_hours=20.0,
            confidence="high",
            basis="test",
        ),
        TopicEstimate(
            course_code="PHYS234",
            topic_id="ch2",
            estimated_hours=20.0,
            confidence="high",
            basis="test",
        ),
    ]
    constraints = UserConstraints(
        start_date="2026-02-10",
        hours_weekday=1.0,
        hours_weekend=1.0,
        priority_weights={},
        notes="",
    )

    rows, summary = planner.build_plan(estimates, constraints, course_specs)
    assert rows
    assert summary.feasible is False
    assert len(summary.warnings) == 3


def test_planner_balances_hours_across_courses_when_feasible() -> None:
    planner = PlanningAgent()
    course_specs = {
        "SYSD300": CourseSpec(
            course_code="SYSD300",
            exam_date="2026-02-24",
            topics=[TopicSpec(topic_id=f"ch{i}", label=f"Chapter {i}") for i in range(1, 5)],
            source_files=[],
            confidence="high",
        ),
        "PHYS234": CourseSpec(
            course_code="PHYS234",
            exam_date="2026-02-26",
            topics=[TopicSpec(topic_id=f"ch{i}", label=f"Chapter {i}") for i in range(1, 5)],
            source_files=[],
            confidence="high",
        ),
        "HLTH204": CourseSpec(
            course_code="HLTH204",
            exam_date="2026-02-27",
            topics=[TopicSpec(topic_id=f"ch{i}", label=f"Chapter {i}") for i in range(1, 5)],
            source_files=[],
            confidence="high",
        ),
    }
    estimates = [
        TopicEstimate(
            course_code="SYSD300",
            topic_id="ch1",
            estimated_hours=8.0,
            confidence="high",
            basis="test",
        ),
        TopicEstimate(
            course_code="PHYS234",
            topic_id="ch1",
            estimated_hours=10.0,
            confidence="high",
            basis="test",
        ),
        TopicEstimate(
            course_code="HLTH204",
            topic_id="ch1",
            estimated_hours=6.0,
            confidence="high",
            basis="test",
        ),
    ]
    constraints = UserConstraints(
        start_date="2026-02-09",
        hours_weekday=3.0,
        hours_weekend=6.0,
        priority_weights={"PHYS234": 1.2},
        notes="",
    )

    rows, summary = planner.build_plan(estimates, constraints, course_specs)
    assert rows
    assert summary.feasible is True
    assert summary.warnings == []

    topic_hours_by_course = defaultdict(float)
    for row in rows:
        if row.topic_id == "final_review":
            continue
        topic_hours_by_course[row.course_code] += row.hours

    assert topic_hours_by_course["SYSD300"] > 0.0
    assert topic_hours_by_course["PHYS234"] > 0.0
    assert topic_hours_by_course["HLTH204"] > 0.0
