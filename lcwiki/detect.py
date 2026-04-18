"""File discovery, classification, and corpus check for LLM Wiki."""

import hashlib
import re
from pathlib import Path

# Supported file extensions by type
DOCUMENT_EXTENSIONS = {".md", ".txt", ".rst"}
PAPER_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {".docx", ".doc", ".xlsx", ".xls", ".pptx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".ogg"}

# Thresholds
MAX_INBOX_FILES = 200
MAX_INBOX_WORDS = 2_000_000

# Files that may contain secrets - skip silently
_SENSITIVE_PATTERNS = [
    re.compile(r"(^|[\\/])\.(env|envrc)(\.|$)", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx|cert|crt|der|p8)$", re.IGNORECASE),
    re.compile(r"(credential|secret|passwd|password|token|private_key)", re.IGNORECASE),
    re.compile(r"(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?$"),
    re.compile(r"(\.netrc|\.pgpass|\.htpasswd)$", re.IGNORECASE),
]

_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "venv", ".venv", "dist", "build", ".eggs",
}


def _is_sensitive(path: Path) -> bool:
    """Return True if this file likely contains secrets."""
    name = path.name
    full = str(path)
    return any(p.search(name) or p.search(full) for p in _SENSITIVE_PATTERNS)


def _classify_file(path: Path) -> str | None:
    """Classify a file by extension. Returns type string or None if unsupported."""
    ext = path.suffix.lower()
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    if ext in PAPER_EXTENSIONS:
        return "paper"
    if ext in OFFICE_EXTENSIONS:
        return "office"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def file_sha256(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def count_words(path: Path) -> int:
    """Estimate word count for a file."""
    from lcwiki.convert import docx_to_markdown, xlsx_to_markdown, extract_pdf_text
    try:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return len(extract_pdf_text(path).split())
        if ext in (".docx", ".doc"):
            return len(docx_to_markdown(path).split())
        if ext in (".xlsx", ".xls"):
            return len(xlsx_to_markdown(path).split())
        if ext in VIDEO_EXTENSIONS:
            return 0  # video word count unknown without transcription
        return len(path.read_text(encoding="utf-8", errors="replace").split())
    except Exception:
        return 0


def detect(inbox_path: Path) -> dict:
    """Scan a directory and classify all supported files.

    Returns:
        dict with keys:
            files: dict[str, list[str]] - files grouped by type
            total_files: int
            total_words: int
            skipped_sensitive: int
            warning: str | None
    """
    files: dict[str, list[str]] = {
        "document": [],
        "paper": [],
        "office": [],
        "image": [],
        "video": [],
    }
    skipped_sensitive = 0
    total_words = 0

    if not inbox_path.exists():
        return {
            "files": files,
            "total_files": 0,
            "total_words": 0,
            "skipped_sensitive": 0,
            "warning": f"Directory not found: {inbox_path}",
        }

    for item in sorted(inbox_path.rglob("*")):
        if not item.is_file():
            continue

        # Skip hidden files and excluded directories
        parts = item.relative_to(inbox_path).parts
        if any(p.startswith(".") for p in parts):
            continue
        if any(p in _SKIP_DIRS for p in parts):
            continue

        # Skip sensitive files
        if _is_sensitive(item):
            skipped_sensitive += 1
            continue

        file_type = _classify_file(item)
        if file_type is None:
            continue

        files[file_type].append(str(item))
        total_words += count_words(item)

    total_files = sum(len(v) for v in files.values())

    # Generate warnings
    warning = None
    if total_files == 0:
        warning = "No supported files found."
    elif total_files > MAX_INBOX_FILES or total_words > MAX_INBOX_WORDS:
        warning = f"Large corpus: {total_files} files, ~{total_words:,} words. Consider processing a subfolder."

    return {
        "files": files,
        "total_files": total_files,
        "total_words": total_words,
        "skipped_sensitive": skipped_sensitive,
        "warning": warning,
    }
