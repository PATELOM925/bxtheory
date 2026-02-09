from __future__ import annotations

import csv
from pathlib import Path

from ..models import PlanRow
from ..models import PlanSummary


CSV_HEADERS = ["date", "course_code", "task_type", "topic_id", "topic_label", "hours", "notes"]


def export_plan(
    plan_rows: list[PlanRow], summary: PlanSummary, output_dir: str
) -> dict[str, str]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "study_plan.csv"
    md_path = out_dir / "study_plan.md"

    _write_csv(plan_rows, csv_path)
    _write_markdown(plan_rows, summary, md_path)

    return {"csv_path": str(csv_path), "md_path": str(md_path)}


def _write_csv(rows: list[PlanRow], path: Path) -> None:
    ordered_rows = sorted(rows, key=lambda row: (row.date, row.course_code, row.topic_id, row.task_type))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in ordered_rows:
            writer.writerow(row.model_dump())


def _write_markdown(rows: list[PlanRow], summary: PlanSummary, path: Path) -> None:
    ordered_rows = sorted(rows, key=lambda row: (row.date, row.course_code, row.topic_id, row.task_type))
    lines: list[str] = []
    lines.append("# Study Plan")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Total planned hours: {summary.total_hours:.2f}")
    lines.append(f"- Feasible: {'Yes' if summary.feasible else 'No'}")
    for course_code in sorted(summary.hours_by_course):
        lines.append(f"- {course_code}: {summary.hours_by_course[course_code]:.2f} hours")
    if summary.warnings:
        lines.append("")
        lines.append("## Warnings")
        for warning in summary.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("## Day-by-Day Plan")
    lines.append("")
    lines.append("| Date | Course | Task | Topic | Hours | Notes |")
    lines.append("|---|---|---|---|---:|---|")
    for row in ordered_rows:
        lines.append(
            f"| {row.date} | {row.course_code} | {row.task_type} | "
            f"{row.topic_label} | {row.hours:.2f} | {row.notes} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
