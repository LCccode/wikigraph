"""Update / replace an existing source file in the kb.

Use case: a .docx was compiled into the wiki, then the user edited the .docx
and wants to re-ingest. Because lcwiki dedupes by sha256, the edited file
would be treated as a new file (different content → different sha), leaving
old article/concept/task artifacts stale in the kb. This module cleans those
stale artifacts by original filename so the new version can be ingested
cleanly.

Public API:
    find_matching_records(kb_root, filename_pattern)
        → list of source_map records whose original_filename contains the pattern.
    plan_removal(kb_root, sha256)
        → dry-run plan listing everything that would be removed.
    apply_removal(plan, kb_root, hard_delete=False)
        → execute plan; moves files to `.trash/<timestamp>/` by default so
          removal is reversible.

Safety:
  - Default is soft-delete (move to .trash/). Nothing is lost until the user
    manually empties .trash/.
  - All steps dry-runnable: use plan_removal alone to inspect before applying.
  - The skill wraps this with mandatory user-confirmation UX.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


def find_matching_records(
    kb_root: Path,
    filename_pattern: str,
) -> list[dict]:
    """Find records in source_map whose original_filename contains the pattern
    (case-insensitive substring match). Returns list of dicts:
        {"sha256", "original_filename", "raw_path", "generated_pages", ...}.
    """
    sm_path = kb_root / "vault" / "meta" / "source_map.json"
    if not sm_path.exists():
        return []
    try:
        sm = json.loads(sm_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    needle = (filename_pattern or "").lower()
    matches = []
    for sha, info in sm.items():
        orig = (info.get("original_filename") or "").lower()
        if needle and needle in orig:
            matches.append({"sha256": sha, **info})
    return matches


def plan_removal(kb_root: Path, sha256: str) -> dict:
    """Build a dry-run removal plan for one sha256 record. No file changes."""
    sm_path = kb_root / "vault" / "meta" / "source_map.json"
    sm = {}
    if sm_path.exists():
        try:
            sm = json.loads(sm_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            sm = {}
    info = sm.get(sha256, {})

    plan: dict = {
        "sha256": sha256,
        "original_filename": info.get("original_filename", ""),
        "article_files": [],
        "archive_dir": None,
        "staging_tasks": [],
        "source_map_entry": sha256 in sm,
        "concept_pages_affected": [],
    }

    for rel in info.get("generated_pages", []) or []:
        p = kb_root / rel
        if p.exists():
            plan["article_files"].append(p)

    if info.get("raw_path"):
        p = kb_root / info["raw_path"]
        if p.exists():
            plan["archive_dir"] = p

    # Tasks in any staging bucket with this sha256
    for sub in ("pending", "processing", "review", "done", "failed"):
        d = kb_root / "staging" / sub
        if not d.exists():
            continue
        for t in d.glob("*.json"):
            try:
                data = json.loads(t.read_text(encoding="utf-8"))
                if data.get("sha256") == sha256:
                    plan["staging_tasks"].append(t)
            except (json.JSONDecodeError, OSError):
                pass

    # Concepts referencing this article (by [[article_title]] wiki-link)
    # Those concept pages stay, but their ## 相关文章 / ## 在方案中的应用 sections
    # may point at deleted articles. We only report — don't auto-modify.
    for rel in info.get("generated_pages", []) or []:
        article_title = Path(rel).stem
        concepts_dir = kb_root / "vault" / "wiki" / "concepts"
        if concepts_dir.exists():
            for c in concepts_dir.glob("*.md"):
                try:
                    if f"[[{article_title}]]" in c.read_text(encoding="utf-8"):
                        plan["concept_pages_affected"].append(c)
                except OSError:
                    pass

    return plan


def apply_removal(
    plan: dict,
    kb_root: Path,
    hard_delete: bool = False,
) -> dict:
    """Execute the removal plan.

    hard_delete=False (default): move files to `<kb>/.trash/<timestamp>/`.
    hard_delete=True: unlink / rmtree irrecoverably.

    Returns a report dict of what was actually removed.
    """
    report = {
        "articles_removed": [],
        "archive_moved": None,
        "tasks_removed": [],
        "source_map_removed": False,
        "trash_dir": None,
    }

    trash_dir = None
    if not hard_delete:
        trash_dir = kb_root / ".trash" / datetime.now().strftime("%Y%m%d_%H%M%S") / plan["sha256"][:8]
        trash_dir.mkdir(parents=True, exist_ok=True)
        report["trash_dir"] = str(trash_dir)

    # articles
    for p in plan["article_files"]:
        if p.exists():
            if hard_delete:
                p.unlink()
            else:
                shutil.move(str(p), str(trash_dir / p.name))
            report["articles_removed"].append(str(p))

    # archive dir
    if plan["archive_dir"] and plan["archive_dir"].exists():
        if hard_delete:
            shutil.rmtree(plan["archive_dir"])
        else:
            shutil.move(str(plan["archive_dir"]), str(trash_dir / plan["archive_dir"].name))
        report["archive_moved"] = str(plan["archive_dir"])

    # staging tasks
    for t in plan["staging_tasks"]:
        if t.exists():
            if hard_delete:
                t.unlink()
            else:
                shutil.move(str(t), str(trash_dir / t.name))
            report["tasks_removed"].append(str(t))

    # source_map entry
    sm_path = kb_root / "vault" / "meta" / "source_map.json"
    if plan["source_map_entry"] and sm_path.exists():
        try:
            sm = json.loads(sm_path.read_text(encoding="utf-8"))
            if plan["sha256"] in sm:
                del sm[plan["sha256"]]
                sm_path.write_text(
                    json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                report["source_map_removed"] = True
        except (json.JSONDecodeError, OSError):
            pass

    # FIX-A: 同步 filename_index 反向索引（仅在文件存在时维护，旧 KB 冷启动安全）
    from lcwiki.index import (
        load_filename_index,
        save_filename_index,
        filename_index_remove,
    )
    meta_dir = kb_root / "vault" / "meta"
    fi_path = meta_dir / "filename_index.json"
    if fi_path.exists():
        try:
            fi = load_filename_index(meta_dir)
            filename_index_remove(plan["sha256"], fi)
            save_filename_index(fi, meta_dir)
        except (OSError, json.JSONDecodeError):
            pass

    return report


def find_inbox_conflicts(kb_root: Path) -> list[dict]:
    """Find files currently in raw/inbox/ whose name matches an already-ingested
    source_map record. These are the likely "user updated an existing file"
    cases that `/lcwiki update` should warn about.

    Returns list of:
        {"inbox_file": Path, "existing_records": [record, ...]}
    """
    inbox = kb_root / "raw" / "inbox"
    if not inbox.exists():
        return []
    conflicts = []
    for f in sorted(inbox.iterdir()):
        if f.is_dir() or f.name.startswith("."):
            continue
        existing = find_matching_records(kb_root, f.stem)
        if existing:
            conflicts.append({"inbox_file": f, "existing_records": existing})
    return conflicts
