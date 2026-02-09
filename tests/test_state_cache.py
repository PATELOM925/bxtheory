from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from multi_tool_agent.agents.orchestrator import KEY_COURSE_SPECS
from multi_tool_agent.agents.orchestrator import KEY_CONSTRAINTS
from multi_tool_agent.agents.orchestrator import KEY_ESTIMATES
from multi_tool_agent.agents.orchestrator import KEY_FILES
from multi_tool_agent.agents.orchestrator import KEY_HITL_HISTORY
from multi_tool_agent.agents.orchestrator import KEY_HITL_PROFILE
from multi_tool_agent.agents.orchestrator import OrchestratorEngine


@dataclass
class DummyToolContext:
    state: dict


def test_upload_once_cache(tmp_path: Path) -> None:
    file_path = tmp_path / "SYSD 300 - Midterm 1 Overview.txt"
    file_path.write_text("Date: February 24, 2026\nCoverage: Chapters 1,2,3\n", encoding="utf-8")

    engine = OrchestratorEngine(module_dir=str(tmp_path))
    first_batch, files_by_sha = engine.ingestion_agent.register_files([str(file_path)], {})
    second_batch, files_by_sha = engine.ingestion_agent.register_files(
        [str(file_path)], files_by_sha
    )

    assert len(first_batch) == 1
    assert len(second_batch) == 1
    assert first_batch[0].sha256 == second_batch[0].sha256
    assert len(files_by_sha) == 1
    assert first_batch[0].gemini_file_id == second_batch[0].gemini_file_id


def test_multi_step_state_persistence(tmp_path: Path) -> None:
    midterm = tmp_path / "PHYS 234 - Midterm 1 Overview.txt"
    textbook = tmp_path / "PHYS 234 - Quantum Textbook.txt"
    midterm.write_text(
        "Date: February 26, 2026\nCoverage: Chapters 1, 2, 3, 4, 5, 6\n",
        encoding="utf-8",
    )
    textbook.write_text("Chapter 1: Intro\nChapter 2: Operators\n", encoding="utf-8")

    ctx = DummyToolContext(state={})
    engine = OrchestratorEngine(module_dir=str(tmp_path))
    engine.register_files([str(midterm), str(textbook)], tool_context=ctx)  # type: ignore[arg-type]
    engine.extract_course_specs(tool_context=ctx)  # type: ignore[arg-type]
    engine.set_constraints(
        constraints_json='{"start_date":"2026-02-10","hours_weekday":2,"hours_weekend":3}',
        tool_context=ctx,  # type: ignore[arg-type]
    )
    engine.estimate_topic_hours(tool_context=ctx)  # type: ignore[arg-type]

    assert KEY_FILES in ctx.state and ctx.state[KEY_FILES]
    assert KEY_COURSE_SPECS in ctx.state and ctx.state[KEY_COURSE_SPECS]
    assert KEY_ESTIMATES in ctx.state and ctx.state[KEY_ESTIMATES]


def test_hitl_profile_is_applied_and_persisted(tmp_path: Path) -> None:
    midterm = tmp_path / "PHYS 234 - Midterm 1 Overview.txt"
    textbook = tmp_path / "PHYS 234 - Quantum Textbook.txt"
    midterm.write_text(
        "Date: February 26, 2026\nCoverage: Chapters 1, 2, 3, 4, 5, 6\n",
        encoding="utf-8",
    )
    textbook.write_text("Chapter 1: Intro\nChapter 2: Operators\n", encoding="utf-8")

    ctx = DummyToolContext(state={})
    engine = OrchestratorEngine(module_dir=str(tmp_path))
    engine.register_files([str(midterm), str(textbook)], tool_context=ctx)  # type: ignore[arg-type]
    engine.extract_course_specs(tool_context=ctx)  # type: ignore[arg-type]

    questions = engine.get_hitl_questions(tool_context=ctx)  # type: ignore[arg-type]
    assert questions["hitl_questions"]

    engine.apply_hitl_profile(
        answers_json=(
            '{"ranked_courses":["PHYS234"],'
            '"familiarity_by_course":{"PHYS234":1},'
            '"coverage_by_course":{"PHYS234":20},'
            '"weakness_by_course":{"PHYS234":5},'
            '"hours":{"hours_weekday":4,"hours_weekend":7}}'
        ),
        tool_context=ctx,  # type: ignore[arg-type]
    )

    assert KEY_CONSTRAINTS in ctx.state
    constraints = ctx.state[KEY_CONSTRAINTS]
    assert constraints["familiarity_by_course"]["PHYS234"] == 1.0
    assert constraints["coverage_by_course"]["PHYS234"] == 20.0
    assert constraints["weakness_by_course"]["PHYS234"] == 5.0
    assert constraints["priority_weights"]["PHYS234"] > 1.0
    assert constraints["hours_weekday"] == 4.0
    assert constraints["hours_weekend"] == 7.0
    assert KEY_HITL_PROFILE in ctx.state


def test_run_study_planner_reports_missing_sources() -> None:
    ctx = DummyToolContext(state={})
    engine = OrchestratorEngine(module_dir="/tmp")
    result = asyncio.run(
        engine.run_study_planner(
            file_paths=[],
            constraints_json='{"start_date":"2026-02-10"}',
            tool_context=ctx,  # type: ignore[arg-type]
        )
    )
    assert "No available files" in result["message"]
    assert any("No files were registered" in warning for warning in result["warnings"])


def test_hitl_history_is_capped_to_ten_entries(tmp_path: Path) -> None:
    midterm = tmp_path / "SYSD 300 - Midterm 1 Overview.txt"
    midterm.write_text(
        "Date: February 24, 2026\nCoverage: Chapters 1, 2, 3\n",
        encoding="utf-8",
    )

    ctx = DummyToolContext(state={})
    engine = OrchestratorEngine(module_dir=str(tmp_path))
    engine.register_files([str(midterm)], tool_context=ctx)  # type: ignore[arg-type]

    for _ in range(4):
        engine.extract_course_specs(tool_context=ctx)  # type: ignore[arg-type]

    assert KEY_HITL_HISTORY in ctx.state
    assert len(ctx.state[KEY_HITL_HISTORY]) == 10


def test_register_files_warns_on_unknown_file_kind(tmp_path: Path) -> None:
    unknown = tmp_path / "PHYS 234 notes.txt"
    unknown.write_text("Random notes", encoding="utf-8")

    ctx = DummyToolContext(state={})
    engine = OrchestratorEngine(module_dir=str(tmp_path))
    result = engine.register_files([str(unknown)], tool_context=ctx)  # type: ignore[arg-type]
    assert result["warnings"]
    assert "Unrecognized file type" in result["warnings"][0]
