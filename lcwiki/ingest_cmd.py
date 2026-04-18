"""Atomic implementation of `/lcwiki ingest` — the deterministic half.

Replaces the `python3 << 'EOF' ... EOF` heredoc that used to live in
skill.md. ingest is 100% deterministic (hash / classify / convert via
convert.py / write content.md+structure.json / update source_map). There is
NO LLM judgement anywhere in this pipeline, so it should never have been a
heredoc that an agent could "understand and rewrite". This module gives it
a single atomic CLI: `lcwiki ingest-run --kb KB [--no-auto-update]`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def run_ingest(kb: Path, auto_update: bool = True) -> dict:
    """Run the smart-ingest pipeline end-to-end.

    Returns the classification report from ingest_inbox.
    """
    from lcwiki.compile import init_kb
    from lcwiki.ingest import ingest_inbox, render_ingest_report

    init_kb(kb)
    report = ingest_inbox(kb, auto_update=auto_update)
    print(render_ingest_report(report))

    if not (report["new"] or report["updated"]):
        print("\n(没有新建 staging task，compile/graph 无事可做)")
    else:
        n = len(report["new"]) + len(report["updated"])
        print(f"\n→ 下一步：/lcwiki compile 会处理这 {n} 个 staging/pending 任务")
    return report


def main(argv: list[str]) -> int:
    kb: Path | None = None
    auto_update = True

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--kb":
            kb = Path(argv[i + 1])
            i += 2
        elif a == "--no-auto-update":
            auto_update = False
            i += 1
        else:
            print(f"error: unknown flag '{a}'", file=sys.stderr)
            return 2

    if kb is None:
        print("usage: lcwiki ingest-run --kb KB_PATH [--no-auto-update]", file=sys.stderr)
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1

    run_ingest(kb, auto_update=auto_update)
    return 0
