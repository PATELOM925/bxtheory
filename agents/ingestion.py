from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from ..models import CourseSpec
from ..models import FileRef
from ..models import TopicSpec
from ..tools import extract_exam_date
from ..tools import extract_text
from ..tools import extract_topics
from ..tools import fallback_exam_date
from ..tools import infer_course_from_file
from ..tools import maybe_upload_file
from ..tools.hash_cache import infer_file_kind
from ..tools.hash_cache import sha256_file


class IngestionAgent:
    #Handles file registration and course-spec extraction

    def register_files(
        self, file_paths: list[str], files_by_sha: dict[str, dict[str, Any]] | None = None
    ) -> tuple[list[FileRef], dict[str, dict[str, Any]]]:
        state_files = dict(files_by_sha or {})
        registered: list[FileRef] = []

        for file_path in file_paths:
            path = Path(file_path).expanduser().resolve()
            if not path.exists():
                continue

            sha = sha256_file(str(path))
            if sha in state_files:
                registered.append(FileRef.model_validate(state_files[sha]))
                continue

            gemini_file_id = maybe_upload_file(str(path), sha)
            file_ref = FileRef(
                sha256=sha,
                filename=path.name,
                local_path=str(path),
                gemini_file_id=gemini_file_id,
                kind=infer_file_kind(path.name),
                uploaded_at=self._iso_now(),
            )
            state_files[sha] = file_ref.model_dump()
            registered.append(file_ref)

        return registered, state_files

    def extract_course_specs(
        self,
        files_by_sha: dict[str, dict[str, Any]],
        start_date: str | None = None,
    ) -> dict[str, CourseSpec]:
        course_specs, _warnings = self.extract_course_specs_with_warnings(
            files_by_sha=files_by_sha,
            start_date=start_date,
        )
        return course_specs

    def extract_course_specs_with_warnings(
        self,
        files_by_sha: dict[str, dict[str, Any]],
        start_date: str | None = None,
    ) -> tuple[dict[str, CourseSpec], list[str]]:
        file_refs = [FileRef.model_validate(value) for value in files_by_sha.values()]
        grouped, unmatched = self._group_files_by_course(file_refs)
        warnings: list[str] = []

        if not file_refs:
            warnings.append(
                "No files are registered in this session. Please register files first."
            )

        for item in unmatched:
            file_ref: FileRef = item["file_ref"]
            reason = item["reason"]
            if reason == "unknown_kind":
                warnings.append(
                    f"File '{file_ref.filename}' has unknown type. Rename it with keywords "
                    "like 'midterm overview', 'syllabus', or 'textbook'."
                )
            else:
                warnings.append(
                    f"File '{file_ref.filename}' could not be mapped to a supported course code."
                )

        if file_refs and not grouped:
            warnings.append(
                "No available course sources after parsing. Please provide recognizable course files."
            )

        course_specs: dict[str, CourseSpec] = {}
        for course_code, records in grouped.items():
            midterm_records = [record for record in records if record["kind"] == "midterm_overview"]
            syllabus_records = [record for record in records if record["kind"] == "syllabus"]
            textbook_records = [record for record in records if record["kind"] == "textbook"]

            exam_date = None
            topics: list[TopicSpec] = []
            confidence = "low"

            for record in midterm_records:
                text = record["text"]
                exam_date = exam_date or extract_exam_date(text)
                if not topics:
                    topics = extract_topics(text)

            if exam_date and topics:
                confidence = "high"

            if not exam_date or not topics:
                for record in syllabus_records:
                    text = record["text"]
                    exam_date = exam_date or extract_exam_date(text)
                    if not topics:
                        topics = extract_topics(text)
                if exam_date or topics:
                    confidence = "medium"

            if not topics:
                for record in textbook_records:
                    topics = extract_topics(record["text"])
                    if topics:
                        break

            if not topics:
                topics = self._default_topics()

            topics = self._dedupe_topics(topics)
            if not exam_date:
                exam_date = fallback_exam_date(start_date=start_date, offset_days=14)
                confidence = "low"

            source_files = [record["file_ref"].local_path for record in records]
            course_specs[course_code] = CourseSpec(
                course_code=course_code,
                exam_name="Midterm 1",
                exam_date=exam_date,
                topics=topics,
                source_files=source_files,
                confidence=confidence,  # type: ignore[arg-type]
            )
            if confidence == "low":
                warnings.append(
                    f"{course_code}: extracted with low confidence, please confirm exam date/topics."
                )

        return dict(sorted(course_specs.items())), warnings

    def _group_files_by_course(
        self, file_refs: list[FileRef]
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        unmatched: list[dict[str, Any]] = []
        for file_ref in file_refs:
            text = extract_text(file_ref.local_path)
            course_code = infer_course_from_file(file_ref.local_path, text)
            if course_code == "UNKNOWN":
                reason = "unknown_kind" if file_ref.kind == "unknown" else "unknown_course"
                unmatched.append({"file_ref": file_ref, "reason": reason})
                continue
            grouped.setdefault(course_code, []).append(
                {"file_ref": file_ref, "kind": file_ref.kind, "text": text}
            )
        return grouped, unmatched

    @staticmethod
    def _default_topics() -> list[TopicSpec]:
        return [
            TopicSpec(topic_id=f"ch{i}", label=f"Chapter {i}", chapter_start=i, chapter_end=i, priority=1.0)
            for i in range(1, 6)
        ]

    @staticmethod
    def _dedupe_topics(topics: list[TopicSpec]) -> list[TopicSpec]:
        deduped: list[TopicSpec] = []
        seen: set[str] = set()
        for topic in topics:
            key = topic.topic_id
            if key in seen:
                continue
            seen.add(key)
            deduped.append(topic)
        return deduped

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
