from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
import os
from pathlib import Path
import re
import subprocess
import tempfile

from ..models import TopicSpec
from .hash_cache import infer_course_code
from .hash_cache import infer_file_kind


MONTH_PATTERN = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)


def extract_text(path: str) -> str:
    kind = infer_file_kind(Path(path).name)
    text_page_cap = 80 if kind == "textbook" else 30
    ocr_page_cap = 10 if kind == "textbook" else 5

    text = _extract_text_pdfplumber(path, max_pages=text_page_cap)
    if len(text.strip()) >= 600:
        return _normalize(text)

    ocr_text = _extract_text_ocr(path, max_pages=ocr_page_cap)
    merged = text + "\n" + ocr_text
    return _normalize(merged)


def _extract_text_pdfplumber(path: str, max_pages: int) -> str:
    try:
        import pdfplumber
    except Exception:
        return ""

    chunks: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:max_pages]:
                chunks.append(page.extract_text() or "")
    except Exception:
        return ""
    return "\n".join(chunks)


def _extract_text_ocr(path: str, max_pages: int) -> str:
    try:
        import fitz
    except Exception:
        return ""

    tesseract_bin = os.getenv("TESSERACT_BIN", "/opt/homebrew/bin/tesseract")
    if not Path(tesseract_bin).exists():
        return ""

    chunks: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception:
        return ""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        for index in range(min(max_pages, len(doc))):
            page = doc[index]
            page_num = index + 1
            image_path = tmp / f"page_{index}.png"
            output_base = tmp / f"ocr_{page_num}"
            page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False).save(str(image_path))
            try:
                subprocess.run(
                    [tesseract_bin, str(image_path), str(output_base), "-l", "eng"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue
            txt_path = Path(str(output_base) + ".txt")
            if txt_path.exists():
                chunks.append(txt_path.read_text(errors="ignore"))
    return "\n".join(chunks)


def _normalize(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line.strip() for line in lines if line.strip())


def extract_exam_date(text: str) -> str | None:
    # Examples: Date: February 24, 2026 / Feb 24 2026
    pattern = re.compile(
        rf"(date[:\s-]*)?{MONTH_PATTERN}\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return None

    month_name = match.group(2)
    day_num = int(match.group(3))
    year_num = int(match.group(4))

    try:
        parsed = datetime.strptime(f"{month_name} {day_num} {year_num}", "%B %d %Y")
    except ValueError:
        parsed = datetime.strptime(f"{month_name} {day_num} {year_num}", "%b %d %Y")
    return parsed.date().isoformat()


def extract_chapter_numbers(text: str) -> list[int]:
    chapters: set[int] = set()

    # Coverage line often has comma-separated values and ranges.
    coverage_match = re.search(
        r"coverage[:\s-]*(chapters?|ch\.?)?\s*([0-9,\-\sandto]+)",
        text,
        re.IGNORECASE,
    )
    if coverage_match:
        chapters.update(_expand_number_list(coverage_match.group(2)))

    for chapter_match in re.finditer(r"chapter\s+(\d+)", text, re.IGNORECASE):
        chapters.add(int(chapter_match.group(1)))

    return sorted(chapters)


def extract_topics(text: str) -> list[TopicSpec]:
    topics: list[TopicSpec] = []
    lines = text.splitlines()

    for line in lines:
        match = re.search(r"chapter\s+(\d+)\s*[:\-]\s*(.+)", line, re.IGNORECASE)
        if not match:
            continue
        chapter = int(match.group(1))
        label = match.group(2).strip(" -")
        topics.append(
            TopicSpec(
                topic_id=f"ch{chapter}",
                label=label or f"Chapter {chapter}",
                chapter_start=chapter,
                chapter_end=chapter,
                priority=1.0,
            )
        )

    chapters = extract_chapter_numbers(text)
    if topics:
        known = {topic.chapter_start for topic in topics if topic.chapter_start is not None}
        for chapter in chapters:
            if chapter in known:
                continue
            topics.append(
                TopicSpec(
                    topic_id=f"ch{chapter}",
                    label=f"Chapter {chapter}",
                    chapter_start=chapter,
                    chapter_end=chapter,
                    priority=1.0,
                )
            )
        return sorted(
            topics,
            key=lambda topic: (
                topic.chapter_start if topic.chapter_start is not None else 10_000,
                topic.topic_id,
            ),
        )

    return topics_from_chapters(chapters)


def topics_from_chapters(chapters: list[int]) -> list[TopicSpec]:
    topics: list[TopicSpec] = []
    for chapter in chapters:
        topics.append(
            TopicSpec(
                topic_id=f"ch{chapter}",
                label=f"Chapter {chapter}",
                chapter_start=chapter,
                chapter_end=chapter,
                priority=1.0,
            )
        )
    return topics


def infer_course_from_file(path: str, text: str) -> str:
    return infer_course_code(Path(path).name, text)


def fallback_exam_date(start_date: str | None = None, offset_days: int = 14) -> str:
    base = date.today() if not start_date else date.fromisoformat(start_date)
    return (base + timedelta(days=offset_days)).isoformat()


def _expand_number_list(raw: str) -> set[int]:
    numbers: set[int] = set()
    if not raw:
        return numbers
    normalized = raw.lower().replace("and", ",").replace("to", "-")
    for token in re.split(r"[,\s]+", normalized):
        if not token:
            continue
        if "-" in token:
            bounds = token.split("-", 1)
            if bounds[0].isdigit() and bounds[1].isdigit():
                start, end = int(bounds[0]), int(bounds[1])
                if start <= end:
                    for value in range(start, end + 1):
                        numbers.add(value)
        elif token.isdigit():
            numbers.add(int(token))
    return numbers
