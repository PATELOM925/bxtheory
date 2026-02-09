from __future__ import annotations

from typing import Any

from ..models import CourseSpec
from ..models import FileRef
from ..models import TopicEstimate
from ..models import UserConstraints
from ..tools.hash_cache import get_pdf_page_count
from ..tools.hash_cache import infer_course_code


DIFFICULTY_MULTIPLIERS = {
    "PHYS234": 1.35,
    "SYSD300": 1.15,
    "HLTH204": 1.00,
}

PAGES_PER_HOUR = 12.0
TASK_MIX_MULTIPLIER = 1.2  # Reading + practice + review blend
DEFAULT_PAGES_PER_CHAPTER = 18.0
MIN_PAGES_PER_CHAPTER = 8.0
MAX_PAGES_PER_CHAPTER = 24.0
TEXTBOOK_CHAPTER_COVERAGE_BUFFER = 4
TEXTBOOK_CHAPTER_COVERAGE_MULTIPLIER = 1.5


class EstimatorAgent:
    """Converts chapter/topic coverage into hour estimates."""

    def estimate_topic_hours(
        self,
        course_specs: dict[str, CourseSpec],
        constraints: UserConstraints,
        files_by_sha: dict[str, dict[str, Any]],
    ) -> list[TopicEstimate]:
        page_map = self._build_textbook_page_map(files_by_sha)
        estimates: list[TopicEstimate] = []

        for course_code in sorted(course_specs):
            spec = course_specs[course_code]
            topics = spec.topics
            if not topics:
                continue

            chapters_in_scope = self._course_chapter_count(topics)
            textbook_pages = page_map.get(course_code, 300)
            pages_per_chapter = self._estimate_pages_per_chapter(
                textbook_pages=textbook_pages,
                chapters_in_scope=chapters_in_scope,
            )
            difficulty = DIFFICULTY_MULTIPLIERS.get(course_code, 1.0)
            priority_boost = constraints.priority_weights.get(course_code, 1.0)
            familiarity = constraints.familiarity_by_course.get(course_code, 3.0)
            weakness = constraints.weakness_by_course.get(course_code, 3.0)
            coverage_percent = constraints.coverage_by_course.get(course_code, 0.0)

            familiarity_multiplier = self._familiarity_multiplier(familiarity)
            weakness_multiplier = self._weakness_multiplier(weakness)
            coverage_multiplier = self._coverage_multiplier(coverage_percent)
            profile_multiplier = familiarity_multiplier * weakness_multiplier * coverage_multiplier

            for topic in topics:
                chapter_width = self._topic_chapter_width(topic.chapter_start, topic.chapter_end)
                pages = pages_per_chapter * chapter_width
                base_hours = pages / PAGES_PER_HOUR
                adjusted_hours = (
                    base_hours
                    * difficulty
                    * TASK_MIX_MULTIPLIER
                    * priority_boost
                    * profile_multiplier
                )
                estimated_hours = max(0.5, round(adjusted_hours, 2))

                basis = (
                    f"pages/chapter={pages_per_chapter:.1f}, pages={pages:.1f}, "
                    f"pph={PAGES_PER_HOUR:.1f}, diff={difficulty:.2f}, "
                    f"mix={TASK_MIX_MULTIPLIER:.2f}, priority={priority_boost:.2f}, "
                    f"familiarity={familiarity_multiplier:.2f}, weakness={weakness_multiplier:.2f}, "
                    f"coverage={coverage_multiplier:.2f}"
                )
                estimates.append(
                    TopicEstimate(
                        course_code=course_code,
                        topic_id=topic.topic_id,
                        estimated_hours=estimated_hours,
                        confidence=spec.confidence,
                        basis=basis,
                    )
                )

        return estimates

    def _build_textbook_page_map(
        self, files_by_sha: dict[str, dict[str, Any]]
    ) -> dict[str, int]:
        page_map: dict[str, int] = {}
        for payload in files_by_sha.values():
            file_ref = FileRef.model_validate(payload)
            if file_ref.kind != "textbook":
                continue
            course_code = infer_course_code(file_ref.filename)
            if course_code == "UNKNOWN":
                continue
            page_count = get_pdf_page_count(file_ref.local_path)
            if page_count <= 0:
                continue
            page_map[course_code] = max(page_map.get(course_code, 0), page_count)
        return page_map

    @staticmethod
    def _course_chapter_count(topics: list[Any]) -> int:
        covered: set[int] = set()
        for topic in topics:
            start = int(topic.chapter_start) if topic.chapter_start is not None else None
            end = int(topic.chapter_end) if topic.chapter_end is not None else start
            if start is None and end is None:
                continue
            if start is None:
                start = end
            if end is None:
                end = start
            if start is None or end is None:
                continue
            lower = min(start, end)
            upper = max(start, end)
            for chapter in range(lower, upper + 1):
                covered.add(chapter)

        if covered:
            return len(covered)
        return max(1, len(topics))

    @staticmethod
    def _topic_chapter_width(start: int | None, end: int | None) -> int:
        if start is None and end is None:
            return 1
        if start is None:
            return max(1, int(end))
        if end is None:
            return 1
        return max(1, int(end) - int(start) + 1)

    @staticmethod
    def _estimate_pages_per_chapter(textbook_pages: int, chapters_in_scope: int) -> float:
        if textbook_pages <= 0:
            return DEFAULT_PAGES_PER_CHAPTER

        inferred_total_chapters = max(
            chapters_in_scope + TEXTBOOK_CHAPTER_COVERAGE_BUFFER,
            int(round(chapters_in_scope * TEXTBOOK_CHAPTER_COVERAGE_MULTIPLIER)),
        )
        raw_pages_per_chapter = textbook_pages / max(1, inferred_total_chapters)
        return min(MAX_PAGES_PER_CHAPTER, max(MIN_PAGES_PER_CHAPTER, raw_pages_per_chapter))

    @staticmethod
    def _familiarity_multiplier(score: float) -> float:
        clamped = min(5.0, max(1.0, float(score)))
        return max(0.75, 1.0 + ((3.0 - clamped) * 0.10))

    @staticmethod
    def _weakness_multiplier(score: float) -> float:
        clamped = min(5.0, max(1.0, float(score)))
        return max(0.70, 1.0 + ((clamped - 3.0) * 0.12))

    @staticmethod
    def _coverage_multiplier(percent_complete: float) -> float:
        clamped = min(100.0, max(0.0, float(percent_complete)))
        completion = clamped / 100.0
        return max(0.35, 1.0 - (0.70 * completion))
