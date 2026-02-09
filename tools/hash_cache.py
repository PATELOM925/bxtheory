from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re

from pypdf import PdfReader

from ..models import FileRef


COURSE_PATTERNS: list[tuple[str, str]] = [
    ("SYSD300", r"(sysd[\s_-]*300|systems?\s+dynamics?)"),
    ("PHYS234", r"(phys[\s_-]*234|quantum)"),
    ("HLTH204", r"(hlth[\s_-]*204|biostat|health)"),
]


def sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def infer_file_kind(filename: str) -> str:
    text = filename.lower()
    if "midterm" in text and "overview" in text:
        return "midterm_overview"
    if "syllabus" in text:
        return "syllabus"
    if "textbook" in text or "sterman" in text or "triola" in text or "quantum" in text:
        return "textbook"
    return "unknown"


def infer_course_code(filename: str, text: str = "") -> str:
    haystack = f"{filename} {text}".lower()
    for course_code, pattern in COURSE_PATTERNS:
        if re.search(pattern, haystack):
            return course_code
    return "UNKNOWN"


def get_pdf_page_count(path: str) -> int:
    try:
        return len(PdfReader(path).pages)
    except Exception:
        return 0


def build_file_ref(path: str, gemini_file_id: str) -> FileRef:
    file_path = Path(path).expanduser().resolve()
    filename = file_path.name
    return FileRef(
        sha256=sha256_file(str(file_path)),
        filename=filename,
        local_path=str(file_path),
        gemini_file_id=gemini_file_id,
        kind=infer_file_kind(filename),
        uploaded_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
