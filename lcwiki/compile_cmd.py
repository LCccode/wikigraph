"""Atomic implementation of `/lcwiki compile` — deterministic halves.

The compile command has three structural phases:

1. PREPARE (deterministic)  — `lcwiki compile-prepare --kb KB`
   Lists pending tasks, snapshots concepts for risk assessment, writes
   /tmp/.lcwiki_compile_tasks.json for the LLM to iterate.

2. LLM GENERATE (not in CLI)
   For each task, LLM reads content.md + images, produces:
     - article markdown (with full frontmatter)
     - concepts list JSON (name/aliases/summary/domain/concept_kind/body_sections)
   These are written to /tmp/lcwiki_compile_<task>_article.md
   and /tmp/lcwiki_compile_<task>_concepts.json.

3. WRITE (deterministic) — `lcwiki compile-write --kb KB --task-id T ...`
   Validates article frontmatter, writes article, builds/updates concept
   pages, updates concepts_index, rolls staging task forward, backfills
   source_map + structure.json.

Separation reason: phase 2 is the only LLM-native work. phases 1 and 3 are
mechanical bookkeeping that the LLM should never "reimplement" — previous
agents have produced empty concept files and frontmatter-less articles
when left to their own devices.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def cmd_prepare(kb: Path) -> int:
    from lcwiki.compile import list_tasks, move_task, take_concepts_snapshot

    tasks = list_tasks(kb / "staging", "pending")
    if not tasks:
        print("[compile] 没有待编译任务")
        return 0

    snapshot = take_concepts_snapshot(kb / "vault" / "meta")
    Path("/tmp/.lcwiki_concepts_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[compile] 概念快照：{len(snapshot)} 个已有概念")

    file_list = []
    for t in tasks:
        content_path = str(kb / t["raw_path"])
        file_list.append(
            {
                "task_id": t["task_id"],
                "sha256": t["sha256"],
                "content_path": content_path,
                "name": Path(t["raw_path"]).parent.name,
            }
        )
        move_task(t, kb / "staging", "processing")

    tasks_file = Path("/tmp/.lcwiki_compile_tasks.json")
    tasks_file.write_text(
        json.dumps(file_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[compile] 待编译：{len(file_list)} 个任务 → {tasks_file}")
    import math

    n_chunks = math.ceil(len(file_list) / 20)
    print(f"[compile] 分 {n_chunks} 个 chunk，每 chunk ≤20 个文件")
    for f in file_list:
        print(f"  {f['task_id']}: {f['name']}")
    return 0


def cmd_write(
    kb: Path,
    task_id: str,
    sha256: str,
    article_title: str,
    article_path: Path,
    concepts_path: Path,
    confidence: float,
    key_terms_path: Path | None = None,
    entities_path: Path | None = None,
    input_chars: int = 0,
) -> int:
    from lcwiki.compile import (
        move_task,
        list_tasks,
        assess_risk,
        update_wiki_index,
        log_compile,
        validate_article_frontmatter,
        validate_concept_frontmatter,
        build_concept_markdown,
        update_concept_markdown,
    )
    from lcwiki.index import (
        ConceptsIndexWriter,
        append_event,
        load_source_map,
        save_source_map,
    )

    start_time = time.time()
    article_content = article_path.read_text(encoding="utf-8")
    concepts = json.loads(concepts_path.read_text(encoding="utf-8"))

    if not isinstance(concepts, list):
        print("error: concepts file must contain a JSON list", file=sys.stderr)
        return 1
    if len(concepts) < 3:
        print(
            f"error: concepts list has {len(concepts)} entries (< 3 required). "
            "Every article MUST identify ≥3 concepts; re-read the document.",
            file=sys.stderr,
        )
        return 1

    validate_article_frontmatter(article_content)

    safe_title = "".join(c for c in article_title if c not in r'\/*?:"<>|')[:80]
    article_out = kb / "vault" / "wiki" / "articles" / f"{safe_title}.md"
    article_out.parent.mkdir(parents=True, exist_ok=True)
    article_out.write_text(article_content, encoding="utf-8")

    writer = ConceptsIndexWriter(kb / "vault" / "meta", task_id)
    for c in concepts:
        cname = c["name"]
        safe_c = "".join(ch for ch in cname if ch not in r'\/*?:"<>|')
        cpath = kb / "vault" / "wiki" / "concepts" / f"{safe_c}.md"
        cpath.parent.mkdir(parents=True, exist_ok=True)
        if not cpath.exists():
            content = build_concept_markdown(
                cname,
                summary=c.get("summary", ""),
                aliases=c.get("aliases", []),
                article_title=article_title,
                domain=c.get("domain", []),
                concept_kind=c.get("concept_kind", "other"),
                body_sections=c.get("body_sections"),
            )
            validate_concept_frontmatter(content)
            cpath.write_text(content, encoding="utf-8")
        else:
            text = cpath.read_text(encoding="utf-8")
            cpath.write_text(update_concept_markdown(text, article_title), encoding="utf-8")
        writer.update(
            cname,
            f"concepts/{safe_c}.md",
            summary=c.get("summary", ""),
            aliases=c.get("aliases", []),
        )
    writer.flush()

    snapshot_path = Path("/tmp/.lcwiki_concepts_snapshot.json")
    snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else {}
    risk = assess_risk([c["name"] for c in concepts], snapshot, confidence)

    task_list = [
        t for t in list_tasks(kb / "staging", "processing") if t["task_id"] == task_id
    ]
    if task_list:
        task = task_list[0]
        move_task(task, kb / "staging", "review" if risk == "review" else "done")

    took = time.time() - start_time
    log_compile(
        kb,
        task_id,
        article_title,
        len(concepts),
        confidence,
        risk,
        input_chars,
        len(article_content),
        took,
    )
    update_wiki_index(kb / "vault" / "wiki")
    append_event(
        kb / "raw" / "index.jsonl",
        {
            "sha256": sha256,
            "event": "wiki_updated",
            "pages": [str(article_out.relative_to(kb))],
        },
    )

    # Backfill source_map
    smap = load_source_map(kb / "vault" / "meta")
    if sha256 in smap:
        smap[sha256]["generated_pages"] = [str(article_out.relative_to(kb))]
        save_source_map(smap, kb / "vault" / "meta")

    # Backfill structure.json with LLM key_terms / entities
    if key_terms_path or entities_path:
        all_tasks = list_tasks(kb / "staging", "review") + list_tasks(kb / "staging", "done")
        match = [t for t in all_tasks if t.get("sha256", "").startswith(sha256[:8])]
        if match:
            content_md_path = kb / match[0]["raw_path"]
            structure_path = content_md_path.parent / "structure.json"
            if structure_path.exists():
                structure = json.loads(structure_path.read_text(encoding="utf-8"))
                if key_terms_path and key_terms_path.exists():
                    structure["key_terms_llm"] = json.loads(
                        key_terms_path.read_text(encoding="utf-8")
                    )
                if entities_path and entities_path.exists():
                    structure["entities"] = json.loads(
                        entities_path.read_text(encoding="utf-8")
                    )
                structure_path.write_text(
                    json.dumps(structure, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    print(
        f"✓ {article_title}: {len(concepts)} concepts, conf={confidence}, risk={risk}, backfill=OK"
    )
    return 0


def main_prepare(argv: list[str]) -> int:
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
        print("usage: lcwiki compile-prepare --kb KB_PATH", file=sys.stderr)
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1
    return cmd_prepare(kb)


def main_write(argv: list[str]) -> int:
    required = {
        "kb": None,
        "task-id": None,
        "sha256": None,
        "title": None,
        "article": None,
        "concepts": None,
        "confidence": None,
    }
    optional = {
        "key-terms": None,
        "entities": None,
        "input-chars": "0",
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a[2:]
            if key in required:
                required[key] = argv[i + 1]
                i += 2
                continue
            if key in optional:
                optional[key] = argv[i + 1]
                i += 2
                continue
        print(f"error: unknown or malformed flag '{a}'", file=sys.stderr)
        return 2

    missing = [k for k, v in required.items() if v is None]
    if missing:
        print(
            "usage: lcwiki compile-write --kb KB --task-id T --sha256 SHA --title TITLE "
            "--article ARTICLE.md --concepts CONCEPTS.json --confidence 0.90 "
            "[--key-terms TERMS.json] [--entities ENTITIES.json] [--input-chars N]",
            file=sys.stderr,
        )
        print(f"missing: {missing}", file=sys.stderr)
        return 2

    kb = Path(required["kb"])
    article_path = Path(required["article"])
    concepts_path = Path(required["concepts"])
    key_terms_path = Path(optional["key-terms"]) if optional["key-terms"] else None
    entities_path = Path(optional["entities"]) if optional["entities"] else None

    if not kb.exists():
        print(f"error: kb not found: {kb}", file=sys.stderr)
        return 1
    if not article_path.exists():
        print(f"error: article file not found: {article_path}", file=sys.stderr)
        return 1
    if not concepts_path.exists():
        print(f"error: concepts file not found: {concepts_path}", file=sys.stderr)
        return 1

    try:
        return cmd_write(
            kb=kb,
            task_id=required["task-id"],
            sha256=required["sha256"],
            article_title=required["title"],
            article_path=article_path,
            concepts_path=concepts_path,
            confidence=float(required["confidence"]),
            key_terms_path=key_terms_path,
            entities_path=entities_path,
            input_chars=int(optional["input-chars"]),
        )
    except Exception as e:
        print(f"error: compile-write failed: {e}", file=sys.stderr)
        return 1


def cmd_reduce(kb: Path) -> int:
    """compile-reduce：合并所有 partial 到 concepts_index.json。

    应在所有 compile-write 调用完成后执行一次。
    """
    from lcwiki.index import ConceptsIndexWriter
    result = ConceptsIndexWriter.reduce(kb / "vault" / "meta")
    print(f"[compile-reduce] 合并完成，concepts_index 共 {len(result)} 个概念")
    return 0


def main_reduce(argv: list[str]) -> int:
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
        print("usage: lcwiki compile-reduce --kb KB_PATH", file=sys.stderr)
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1
    return cmd_reduce(kb)
