from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from google.adk.agents import Agent

from .agents.orchestrator import OrchestratorEngine


def _resolve_model() -> str:
    explicit_model = os.getenv("ADK_MODEL", "").strip()
    if explicit_model:
        return explicit_model

    provider = os.getenv("MODEL_PROVIDER", "gemini").strip().lower()
    has_google_key = bool(os.getenv("GOOGLE_API_KEY", "").strip())
    has_openai_key = bool(os.getenv("OPENAI_API_KEY", "").strip())
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().upper() == "TRUE"

    if provider == "openai":
        if not has_openai_key:
            raise RuntimeError("MODEL_PROVIDER=openai requires OPENAI_API_KEY.")
        if importlib.util.find_spec("litellm") is None:
            raise RuntimeError(
                "OpenAI provider requires LiteLLM. Install with: pip install \"google-adk[extensions]\""
            )
        return os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

    if provider in ("gemini", "auto"):
        if not use_vertex and not has_google_key:
            raise RuntimeError("Gemini mode requires GOOGLE_API_KEY (or Vertex AI envs).")
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()

    raise RuntimeError("MODEL_PROVIDER must be one of: gemini, openai, auto.")


MODEL_ID = _resolve_model()
MODULE_DIR = Path(__file__).resolve().parent
ENGINE = OrchestratorEngine(module_dir=str(MODULE_DIR))

# Explicit 5-agent architecture for the study planner workflow.
hitl_agent = Agent(
    name="hitl_agent",
    model=MODEL_ID,
    description="Collects learner profile, confirms assumptions, and applies user edits.",
    instruction=(
        "You validate ambiguous exam dates/topics and ask targeted user questions "
        "about familiarity, current coverage, weaknesses, and priority ranking. "
        "Use answers to tune planning constraints."
    ),
)

ingestion_agent = Agent(
    name="ingestion_agent",
    model=MODEL_ID,
    description="Registers files once per session and extracts course specs.",
    instruction=(
        "You parse uploaded PDFs, infer exam dates/chapter coverage, and return "
        "typed course specs with confidence."
    ),
)

estimation_agent = Agent(
    name="estimation_agent",
    model=MODEL_ID,
    description="Estimates hours per topic with confidence and assumptions.",
    instruction=(
        "You estimate topic effort from chapter/page scope and course difficulty."
    ),
)

planning_agent = Agent(
    name="planning_agent",
    model=MODEL_ID,
    description="Builds deterministic day-by-day plan with feasibility checks.",
    instruction=(
        "You schedule study tasks by urgency and remaining effort, include spaced review, "
        "and emit exactly three mitigation options if infeasible."
    ),
)

formatting_agent = Agent(
    name="formatting_agent",
    model=MODEL_ID,
    description="Exports deterministic CSV and Markdown artifacts.",
    instruction=(
        "You emit study_plan.csv and study_plan.md with stable schema and ordering."
    ),
)

root_agent = Agent(
    name="exam_study_planner",
    model=MODEL_ID,
    description=(
        "Generates a day-by-day multi-course exam study plan from uploaded PDFs."
    ),
    instruction=(
        "You are the orchestrator for a 5-agent study planner team. "
        "Always persist state in session keys, never require duplicate file uploads, "
        "and use this tool sequence unless user requests otherwise: "
        "register_files -> extract_course_specs -> get_hitl_questions -> apply_hitl_profile -> "
        "set_constraints/apply_hitl_edits -> "
        "estimate_topic_hours -> build_plan -> export_plan. "
        "For one-shot generation use run_study_planner."
    ),
    tools=[
        ENGINE.register_files,
        ENGINE.extract_course_specs,
        ENGINE.get_hitl_questions,
        ENGINE.apply_hitl_profile,
        ENGINE.set_constraints,
        ENGINE.apply_hitl_edits,
        ENGINE.estimate_topic_hours,
        ENGINE.build_plan,
        ENGINE.export_plan,
        ENGINE.run_study_planner,
        ENGINE.get_state_snapshot,
    ],
    sub_agents=[
        hitl_agent,
        ingestion_agent,
        estimation_agent,
        planning_agent,
        formatting_agent,
    ],
)
