"""Smart ingest for `/lcwiki ingest`.

Auto-classifies each file in raw/inbox/ into:
  - **skip**   : sha256 already in source_map AND article already compiled
                 → delete from inbox, don't reprocess (saves compile tokens)
  - **update** : filename stem matches an existing record but with DIFFERENT
                 sha (user edited an existing file) → auto call
                 `lcwiki.update.plan_removal + apply_removal` to soft-delete
                 the old version (to .trash/), then ingest the new one normally
  - **new**    : brand-new file, standard ingest
  - **failed** : conversion error (e.g. .doc format, empty content, corrupted)

The old manual `/lcwiki update <pattern>` command still exists for cases where
the user wants to clean a record without uploading a replacement.

Why smart ingest over manual update:
  - Users just dump files into inbox without mental overhead
  - Prevents the "duplicate ingest wastes compile tokens" bug
  - Prevents the "two versions of the same article cluttering wiki" bug
  - .trash/ keeps everything recoverable
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from lcwiki.convert import convert_file
from lcwiki.structure import extract_structure
from lcwiki.index import (
    update_source_map,
    save_source_map,
    load_source_map,
    append_event,
    load_filename_index,
    save_filename_index,
    rebuild_filename_index,
    filename_index_lookup,
    filename_index_add,
    filename_index_remove,
)
from lcwiki.compile import create_task, save_task
from lcwiki.update import plan_removal, apply_removal


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_inbox(kb_root: Path, auto_update: bool = True) -> dict:
    """Smart-ingest every file in raw/inbox/. Returns a classification report.

    Args:
        kb_root: path to the kb root (contains raw/, vault/, staging/).
        auto_update: if True (default), same-filename-different-sha files
            trigger automatic old-version cleanup. Set False to simulate
            the old "just ingest without dedup" behaviour.

    Returns dict with keys:
        skipped  = [{"name", "sha"}, ...]
        updated  = [{"name", "sha", "old_shas"}, ...]
        new      = [{"name", "sha"}, ...]
        failed   = [{"name", "error"}, ...]
    """
    inbox = kb_root / "raw" / "inbox"
    archive_root = kb_root / "raw" / "archive" / datetime.now().strftime("%Y-%m-%d")
    meta = kb_root / "vault" / "meta"
    staging = kb_root / "staging"

    source_map = load_source_map(meta)
    # 加载反向索引；旧 KB 冷启动时自动重建
    filename_index = load_filename_index(meta)
    if not filename_index and source_map:  # 冷启动：文件不存在或空
        filename_index = rebuild_filename_index(source_map)
        save_filename_index(filename_index, meta)
    report: dict = {"skipped": [], "updated": [], "new": [], "failed": []}

    if not inbox.exists():
        return report

    for f in sorted(inbox.iterdir()):
        if f.is_dir() or f.name.startswith("."):
            continue

        try:
            sha = _file_sha256(f)

            # 1. Already-processed: sha in source_map AND has compiled article
            existing = source_map.get(sha)
            if existing and existing.get("generated_pages"):
                f.unlink()
                report["skipped"].append({"name": f.name, "sha": sha[:12]})
                continue

            # 2. Filename-stem conflict with different sha → auto-update
            # FIX-A: O(1) 反向索引查找，替代原 O(N) 遍历
            conflict_shas = filename_index_lookup(
                f.stem, filename_index, exclude_sha=sha
            )
            if auto_update and conflict_shas:
                for old_sha in conflict_shas:
                    plan = plan_removal(kb_root, old_sha)
                    apply_removal(plan, kb_root, hard_delete=False)
                    # 同步从反向索引移除旧 sha
                    filename_index_remove(old_sha, filename_index)
                # Reload source_map after trash-moving old records
                source_map = load_source_map(meta)
                report["updated"].append({
                    "name": f.name,
                    "sha": sha[:12],
                    "old_shas": [s[:12] for s in conflict_shas],
                })
                is_update = True
            else:
                is_update = False

            # 3. Standard ingest (convert + structure + source_map + task)
            dest = archive_root / f.stem
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest / f"original{f.suffix}")
            md, assets = convert_file(f, assets_dir=dest)
            if len(md.strip()) < 50:
                raise ValueError("content too short (<50 chars)")
            (dest / "content.md").write_text(md, encoding="utf-8")
            (dest / "structure.json").write_text(
                json.dumps(extract_structure(md), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            rel = str(dest.relative_to(kb_root))
            source_map = update_source_map(
                sha256=sha,
                original_filename=f.name,
                raw_path=rel,
                generated_pages=[],
                uploader="manual",
                source_map=source_map,
            )
            task = create_task(sha, rel)
            save_task(task, staging)
            append_event(
                kb_root / "raw" / "index.jsonl",
                {"sha256": sha, "event": "ingested", "filename": f.name},
            )
            # FIX-A: 新 sha 加入反向索引
            filename_index_add(f.stem, sha, filename_index)
            f.unlink()

            if not is_update:
                report["new"].append({"name": f.name, "sha": sha[:12]})
        except Exception as e:
            report["failed"].append({"name": f.name, "error": str(e)})

    save_source_map(source_map, meta)
    save_filename_index(filename_index, meta)
    return report


def render_ingest_report(report: dict) -> str:
    """Format the ingest report for human-readable display in skill output."""
    lines = []
    lines.append(
        f"[ingest] new={len(report['new'])}  updated={len(report['updated'])}  "
        f"skipped={len(report['skipped'])}  failed={len(report['failed'])}"
    )
    if report["new"]:
        lines.append(f"\n  ✨ 新增 ({len(report['new'])}):")
        for r in report["new"]:
            lines.append(f"    + {r['name']}  sha={r['sha']}")
    if report["updated"]:
        lines.append(f"\n  🔄 更新（清旧 + 入新，旧版在 .trash/）({len(report['updated'])}):")
        for r in report["updated"]:
            lines.append(
                f"    ↻ {r['name']}  旧 sha={','.join(r['old_shas'])}  新 sha={r['sha']}"
            )
    if report["skipped"]:
        lines.append(f"\n  ⏭️  跳过（sha 已处理过）({len(report['skipped'])}):")
        for r in report["skipped"]:
            lines.append(f"    = {r['name']}  sha={r['sha']}")
    if report["failed"]:
        lines.append(f"\n  ❌ 失败 ({len(report['failed'])}):")
        for r in report["failed"]:
            lines.append(f"    × {r['name']}  {r['error']}")
    return "\n".join(lines)
