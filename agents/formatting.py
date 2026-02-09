from __future__ import annotations

from pathlib import Path

from ..models import PlanRow
from ..models import PlanSummary
from ..tools.export import export_plan


class FormattingAgent:
    """Exports deterministic CSV and Markdown outputs."""

    def export_plan(
        self,
        plan_rows: list[PlanRow],
        summary: PlanSummary,
        output_dir: str,
    ) -> dict[str, str]:
        return export_plan(plan_rows=plan_rows, summary=summary, output_dir=output_dir)

    @staticmethod
    def default_output_dir(module_dir: str) -> str:
        return str(Path(module_dir).resolve() / "outputs")
