"""Post-ingest output verifier.

Checks that `/lcwiki ingest` produced well-formed ingest artifacts. Purpose:
detect when an upstream agent hand-crafted content.md / structure.json /
source_map entries instead of calling `lcwiki ingest-run`, and refuse to
proceed when ingest state is malformed.

Invariants verified:
- source_map.json exists and is a valid JSON object
- for every sha in source_map: raw_path exists under <kb>/<raw_path>
- every sha directory has content.md (>= 50 chars) and structure.json (valid JSON)
- every staging task (pending/processing/review/done) points to a sha
  present in source_map

Exits non-zero with a structured FAILED: report on any violation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_CONTENT_CHARS = 50


def _fail(msg: str) -> None:
    print(f"FAILED: {msg}", file=sys.stderr)


def verify(kb: Path) -> list[str]:
    errors: list[str] = []

    meta_dir = kb / "vault" / "meta"
    source_map_path = meta_dir / "source_map.json"
    if not source_map_path.exists():
        errors.append("vault/meta/source_map.json missing (ingest never ran?)")
        return errors

    try:
        source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"source_map.json is not valid JSON: {e}")
        return errors

    if not isinstance(source_map, dict):
        errors.append(f"source_map.json must be a dict, got {type(source_map).__name__}")
        return errors

    if not source_map:
        errors.append("source_map.json is empty (no files have been ingested)")
        return errors

    short_contents = []
    missing_content = []
    missing_structure = []
    invalid_structure = []
    missing_raw = []

    for sha, info in source_map.items():
        raw_path_rel = info.get("raw_path") if isinstance(info, dict) else None
        if not raw_path_rel:
            errors.append(f"source_map[{sha[:12]}] has no raw_path")
            continue
        raw_dir = kb / raw_path_rel
        if not raw_dir.exists() or not raw_dir.is_dir():
            missing_raw.append(f"{sha[:12]} -> {raw_path_rel}")
            continue

        content_path = raw_dir / "content.md"
        if not content_path.exists():
            missing_content.append(f"{sha[:12]}/{raw_path_rel}")
        else:
            text = content_path.read_text(encoding="utf-8", errors="replace")
            if len(text.strip()) < MIN_CONTENT_CHARS:
                short_contents.append(
                    f"{sha[:12]}/{raw_path_rel}/content.md ({len(text.strip())} chars, < {MIN_CONTENT_CHARS})"
                )

        structure_path = raw_dir / "structure.json"
        if not structure_path.exists():
            missing_structure.append(f"{sha[:12]}/{raw_path_rel}")
        else:
            try:
                json.loads(structure_path.read_text(encoding="utf-8"))
            except Exception as e:
                invalid_structure.append(f"{sha[:12]}/{raw_path_rel}/structure.json: {e}")

    if missing_raw:
        errors.append(
            f"source_map references {len(missing_raw)} raw_path dirs that do not exist: "
            f"{missing_raw[:5]}{'...' if len(missing_raw) > 5 else ''}"
        )
    if missing_content:
        errors.append(
            f"{len(missing_content)} archive dirs missing content.md: "
            f"{missing_content[:5]}{'...' if len(missing_content) > 5 else ''}"
        )
    if short_contents:
        errors.append(
            f"{len(short_contents)} content.md files are suspiciously short (< {MIN_CONTENT_CHARS} chars; "
            "likely hand-crafted stub): "
            f"{short_contents[:3]}{'...' if len(short_contents) > 3 else ''}"
        )
    if missing_structure:
        errors.append(
            f"{len(missing_structure)} archive dirs missing structure.json: "
            f"{missing_structure[:5]}{'...' if len(missing_structure) > 5 else ''}"
        )
    if invalid_structure:
        errors.append(
            f"{len(invalid_structure)} structure.json files have invalid JSON: "
            f"{invalid_structure[:3]}"
        )

    staging_dir = kb / "staging"
    if staging_dir.exists():
        orphan_tasks = []
        for status_dir in ("pending", "processing", "review", "done"):
            status_path = staging_dir / status_dir
            if not status_path.exists():
                continue
            for task_file in status_path.glob("*.json"):
                try:
                    task = json.loads(task_file.read_text(encoding="utf-8"))
                except Exception:
                    errors.append(f"staging/{status_dir}/{task_file.name} is not valid JSON")
                    continue
                sha = task.get("sha256")
                if sha and sha not in source_map:
                    orphan_tasks.append(f"{status_dir}/{task_file.name} (sha {sha[:12]})")
        if orphan_tasks:
            errors.append(
                f"{len(orphan_tasks)} staging tasks point to sha not in source_map: "
                f"{orphan_tasks[:5]}{'...' if len(orphan_tasks) > 5 else ''}"
            )

    return errors


def main(argv: list[str]) -> int:
    kb: Path | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--kb":
            kb = Path(argv[i + 1])
            i += 2
        else:
            print(f"error: unknown flag '{a}'", file=sys.stderr)
            return 2

    if kb is None:
        print("usage: lcwiki ingest-verify --kb KB_PATH", file=sys.stderr)
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1

    errors = verify(kb)
    if errors:
        print(f"❌ ingest verification FAILED — {len(errors)} problem(s):")
        for e in errors:
            _fail(e)
        print("\n⚠️ Do NOT hand-craft missing files. Run `lcwiki ingest-run --kb KB` after placing files in raw/inbox/.")
        return 1

    print("✅ ingest verification passed — source_map + archive + staging are consistent.")
    return 0
