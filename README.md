# Exam Study Planner (ADK + Gemini)

This agent generates a day-by-day multi-course study plan from uploaded course PDFs.

## Quick Start

```bash
cd /bxtheory
source bxtheory/bin/activate

# Optional: install package deps for this module
pip install -r bxtheory/multi_tool_agent/requirements.txt

cd bxtheory/multi_tool_agent
cp .env.example .env
```

Set `.env` for Gemini:

```env
MODEL_PROVIDER=gemini
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

Run:

```bash
../../bxtheory/bin/adk run .
# or
../../bxtheory/bin/adk web .
```

## Architecture

- `orchestrator` (root)
- `hitl_agent`
- `ingestion_agent`
- `estimation_agent`
- `planning_agent`
- `formatting_agent`

## Session State Keys

- `files_by_sha`
- `course_specs`
- `constraints`
- `topic_estimates`
- `plan_rows`
- `plan_summary`
- `hitl_history`

## Output Artifacts

Generated in both places:

- ADK Web Artifacts panel (session-scoped)
- Local folder `bxtheory/multi_tool_agent/outputs`

- `study_plan.csv`
- `study_plan.md`

## Tool Sequence

Recommended order:

1. `register_files`
2. `extract_course_specs`
3. `get_hitl_questions`
4. `apply_hitl_profile`
5. `set_constraints` / `apply_hitl_edits`
6. `estimate_topic_hours`
7. `build_plan`
8. `export_plan`

One-shot:

- `run_study_planner`
