from __future__ import annotations

import os


def maybe_upload_file(path: str, sha256: str) -> str:
    """Uploads file to Gemini Files API when enabled, otherwise returns local ID."""
    if os.getenv("USE_GEMINI_FILES", "false").strip().lower() != "true":
        return f"local:{sha256[:16]}"

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return f"local:{sha256[:16]}"

    try:
        from google import genai
    except Exception:
        return f"local:{sha256[:16]}"

    try:
        client = genai.Client(api_key=api_key)
        uploaded = client.files.upload(file=path)
        # SDK shape can vary; handle common names.
        file_id = getattr(uploaded, "name", None) or getattr(uploaded, "id", None)
        if isinstance(file_id, str) and file_id:
            return file_id
    except Exception:
        pass

    return f"local:{sha256[:16]}"
