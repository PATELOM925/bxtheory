# GitHub Repository
**Repo Link:** `https://github.com/PATELOM925/bxtheory`

# Exam Study Planner Code Documentation

## 1) What This System Does
This project is a multi-agent exam study planner built with Google ADK.

It takes multiple course PDFs (midterm overviews, syllabi, textbooks), extracts exam scope, asks Human-in-the-Loop (HITL) questions, estimates required study hours, builds a day-by-day schedule, and exports:

- `study_plan.csv`
- `study_plan.md`

Artifacts are available in:

- ADK Web Artifacts panel (session-scoped)
- Local output folder: `bxtheory/multi_tool_agent/outputs`

## 2) High-Level Architecture
The system uses a 5-agent architecture with one orchestrator:

1. `OrchestratorAgent`  
   File: `bxtheory/multi_tool_agent/agents/orchestrator.py`  
   Owns workflow sequencing, state persistence, and final export.

2. `IngestionAgent`  
   File: `bxtheory/multi_tool_agent/agents/ingestion.py`  
   Registers files once per session, parses text, extracts course specs.

3. `HITLAgent`  
   File: `bxtheory/multi_tool_agent/agents/hitl.py`  
   Builds intake questions and applies user-driven overrides and profile adjustments.

4. `EstimatorAgent`  
   File: `bxtheory/multi_tool_agent/agents/estimation.py`  
   Converts topic/chapter scope into estimated hours.

5. `PlanningAgent` + `FormattingAgent`  
   Files:  
   `bxtheory/multi_tool_agent/agents/planning.py`  
   `bxtheory/multi_tool_agent/agents/formatting.py`  
   Planning builds the schedule and feasibility warnings; formatting exports deterministic CSV/Markdown.

Root ADK setup is in:

- `bxtheory/multi_tool_agent/agent.py`

## 3) End-to-End Flow
Typical one-shot flow uses `run_study_planner`:

1. `register_files`
2. `extract_course_specs`
3. `set_constraints`
4. `apply_hitl_profile` (optional, or required when `require_hitl_profile=true`)
5. `apply_hitl_edits` (optional)
6. `estimate_topic_hours`
7. `build_plan`
8. `export_plan`

This is implemented in `OrchestratorEngine.run_study_planner`.

## 4) Session State Contract
State is JSON-serializable and stored in ADK session state.

Keys:

- `files_by_sha`: hash-indexed file references
- `course_specs`: extracted course structure
- `constraints`: normalized planning constraints
- `topic_estimates`: per-topic estimated effort
- `plan_rows`: day-by-day plan rows
- `plan_summary`: totals + feasibility + warnings
- `hitl_history`: capped history of prompts/notes (max 10)
- `hitl_profile`: latest user intake answer payload

## 5) Upload-Once and Caching Behavior
File deduplication is enforced using SHA-256:

- Hash computed via `sha256_file(...)`
- Existing hash in `files_by_sha` => file reused (no re-upload)
- New hash => optional Gemini Files upload (if enabled), else local ID fallback

Relevant files:

- `bxtheory/multi_tool_agent/tools/hash_cache.py`
- `bxtheory/multi_tool_agent/tools/gemini_files.py`
- `bxtheory/multi_tool_agent/agents/ingestion.py`

## 6) Parsing and Extraction Logic
Ingestion uses layered extraction:

- Midterm overview (highest confidence)
- Syllabus (fallback)
- Textbook (topic fallback)
- Default topics + fallback exam date if missing

Extraction utilities:

- `extract_text` (pdf text + OCR fallback)
- `extract_exam_date`
- `extract_topics`
- `fallback_exam_date`

Source:

- `bxtheory/multi_tool_agent/tools/pdf_ingest.py`

## 7) HITL Personalization
HITL collects:

- Ranked course priority
- Familiarity score per course (1 to 5)
- Coverage percent per course (0 to 100)
- Weakness score per course (1 to 5)
- Optional weekday/weekend hours update

These values are blended into `priority_weights` and timing constraints to personalize scheduling.

## 8) Estimation Model
Per-topic estimation uses:

- textbook page count (when available)
- pages-per-hour baseline
- course difficulty multiplier
- task-mix multiplier
- profile multipliers from HITL (familiarity, weakness, coverage)

Output type:

- `TopicEstimate(course_code, topic_id, estimated_hours, confidence, basis)`

## 9) Planning Model
Planner behavior:

- Builds schedule from `start_date` to latest exam date
- Reserves pre-exam final-review buffer
- Assigns study in chunks, adds spaced review cadence
- Applies urgency, shortfall pressure, and user profile weighting
- Detects infeasibility and returns exactly 3 mitigation recommendations

Output:

- `PlanRow[]` + `PlanSummary`

## 10) Exports and Artifacts
`export_plan` creates deterministic outputs:

- `study_plan.csv` (stable headers/order)
- `study_plan.md` (summary, warnings, day-by-day table)

Then orchestrator publishes both files as ADK web artifacts with `tool_context.save_artifact(...)`.

## 11) Type Contracts
Pydantic schemas:

- `FileRef`
- `TopicSpec`
- `CourseSpec`
- `UserConstraints`
- `TopicEstimate`
- `PlanRow`
- `PlanSummary`

Defined in:

- `bxtheory/multi_tool_agent/models/schemas.py`

## 12) Testing Coverage
Current tests validate:

- Upload-once cache behavior
- State persistence across stages
- HITL profile application/persistence
- Graceful handling when no files are provided
- `hitl_history` cap behavior
- Warning for unknown file kinds
- Planner infeasible path with exactly 3 options
- Planner balancing across courses when feasible
- Deterministic export contract
- ADK artifact publishing

Tests located in:

- `bxtheory/multi_tool_agent/tests/test_state_cache.py`
- `bxtheory/multi_tool_agent/tests/test_planner.py`
- `bxtheory/multi_tool_agent/tests/test_exports.py`

## 13) Run Commands
```bash
cd /Users/om-college/Desktop/Work/bxtheory
source bxtheory/bin/activate
cd bxtheory/multi_tool_agent
../../bxtheory/bin/adk web .
```

Run tests:
```bash
cd /Users/om-college/Desktop/Work/bxtheory/bxtheory
./bin/python -m pytest -q multi_tool_agent/tests
```
