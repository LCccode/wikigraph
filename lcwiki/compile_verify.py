"""Post-compile output verifier.

Checks that every article and concept produced by `/lcwiki compile` has the
schema the rest of lcwiki expects. Purpose: detect when an upstream agent
hand-crafted wiki files instead of calling `lcwiki compile-write`, and
refuse to proceed (e.g. to `/lcwiki graph`) when the wiki is incomplete.

Evidence from production: when LLMs skipped the WRITEEOF Python heredoc and
wrote articles manually, articles had no frontmatter, `## 核心摘要` = full
original text, `## 详细内容` = same full text, concept files contained just
`# 核心概念提取` and an empty line. This verifier catches all of that.

Invariants verified:
- every article has valid frontmatter with required fields (title / doc_type /
  source_sha256 / concepts ≥ 3 / compiled_by / confidence / tldr)
- every concept has a concept_kind in the allowed enum + four body sections
  (概要 / 关键特征 / 在方案中的应用 / 相关概念) + total body ≥ 200 chars
- concepts_index.json exists and is valid
- staging pending/processing queue is empty (compile finished)

Exits non-zero with a structured FAILED: report on any violation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from lcwiki.compile import (
    validate_article_frontmatter,
    validate_concept_frontmatter,
    _parse_frontmatter,
)

ALLOWED_CONCEPT_KINDS = {
    "capability", "product", "module", "framework",
    "policy", "metric", "role", "method", "other",
}

REQUIRED_CONCEPT_SECTIONS = ("概要", "关键特征", "在方案中的应用", "相关概念")

MIN_CONCEPT_BODY_CHARS = 200
MIN_ARTICLE_BODY_CHARS = 500
MIN_CONCEPTS_PER_ARTICLE = 3


def _fail(msg: str) -> None:
    print(f"FAILED: {msg}", file=sys.stderr)


def _check_article(path: Path, warnings: list[str] | None = None) -> list[str]:
    errs: list[str] = []
    content = path.read_text(encoding="utf-8", errors="replace")
    try:
        fm = validate_article_frontmatter(content)
    except Exception as e:
        errs.append(f"{path.name}: {e}")
        return errs

    tldr = fm.get("tldr", "")
    if not tldr or len(str(tldr).strip()) < 20:
        errs.append(f"{path.name}: tldr missing or too short (<20 chars)")

    concepts = fm.get("concepts", [])
    if not isinstance(concepts, list) or len(concepts) < MIN_CONCEPTS_PER_ARTICLE:
        errs.append(
            f"{path.name}: concepts list has {len(concepts) if isinstance(concepts, list) else 0} "
            f"entries (< {MIN_CONCEPTS_PER_ARTICLE} required)"
        )

    _, body = _parse_frontmatter(content)
    if len(body.strip()) < MIN_ARTICLE_BODY_CHARS:
        errs.append(
            f"{path.name}: article body {len(body.strip())} chars (< {MIN_ARTICLE_BODY_CHARS}); "
            "looks like an empty stub"
        )

    core_summary = body.count("## 核心摘要")
    detail = body.count("## 详细内容")
    if core_summary and detail:
        idx_summary = body.find("## 核心摘要")
        idx_detail = body.find("## 详细内容")
        if idx_summary >= 0 and idx_detail > idx_summary:
            summary_block = body[idx_summary:idx_detail]
            detail_block = body[idx_detail:]
            if len(summary_block) > 200 and len(detail_block) > 200:
                ratio = min(len(summary_block), len(detail_block)) / max(
                    len(summary_block), len(detail_block)
                )
                if ratio > 0.95 and summary_block[:200] == detail_block.replace(
                    "## 详细内容", "## 核心摘要", 1
                )[:200]:
                    errs.append(
                        f"{path.name}: 核心摘要 and 详细内容 appear identical "
                        "(LLM likely copied content.md twice instead of summarizing)"
                    )

    # FIX-C: aliases 字段检查（默认 warn，LCWIKI_STRICT_ALIASES=1 时升级为 error）
    strict = os.environ.get("LCWIKI_STRICT_ALIASES") == "1"
    aliases = fm.get("aliases")
    if "aliases" not in fm:
        msg = f"{path.name}: aliases 字段缺失（required since v0.6）"
        if strict:
            errs.append(msg)
        elif warnings is not None:
            warnings.append(msg)
    elif not isinstance(aliases, list):
        # 非 list 一律 error（LLM 输出格式错误，不是兼容性问题）
        errs.append(
            f"{path.name}: aliases 必须是 list，当前类型 {type(aliases).__name__}"
        )

    return errs


def _check_concept(path: Path) -> list[str]:
    errs: list[str] = []
    content = path.read_text(encoding="utf-8", errors="replace")
    try:
        fm = validate_concept_frontmatter(content)
    except Exception as e:
        errs.append(f"{path.name}: {e}")
        return errs

    kind = fm.get("concept_kind", "")
    if kind not in ALLOWED_CONCEPT_KINDS:
        errs.append(
            f"{path.name}: concept_kind='{kind}' not in allowed set "
            f"({sorted(ALLOWED_CONCEPT_KINDS)})"
        )

    _, body = _parse_frontmatter(content)
    missing_sections = [
        s for s in REQUIRED_CONCEPT_SECTIONS if f"## {s}" not in body
    ]
    if missing_sections:
        errs.append(
            f"{path.name}: missing required sections {missing_sections}; "
            "every concept must have 概要/关键特征/在方案中的应用/相关概念"
        )

    if len(body.strip()) < MIN_CONCEPT_BODY_CHARS:
        errs.append(
            f"{path.name}: body {len(body.strip())} chars (< {MIN_CONCEPT_BODY_CHARS}); "
            "likely an empty stub — did LLM actually populate body_sections?"
        )
    return errs


def verify(kb: Path, warnings: list[str] | None = None) -> list[str]:
    errors: list[str] = []

    articles_dir = kb / "vault" / "wiki" / "articles"
    concepts_dir = kb / "vault" / "wiki" / "concepts"

    if not articles_dir.exists():
        errors.append(f"articles dir missing: {articles_dir}")
    else:
        articles = sorted(articles_dir.glob("*.md"))
        if not articles:
            errors.append("vault/wiki/articles/ has no *.md files")
        else:
            for p in articles:
                errors.extend(_check_article(p, warnings=warnings))

    if not concepts_dir.exists():
        errors.append(f"concepts dir missing: {concepts_dir}")
    else:
        concepts = sorted(concepts_dir.glob("*.md"))
        if not concepts:
            errors.append("vault/wiki/concepts/ has no *.md files")
        else:
            # Catch the forged "08926643_concepts.md" pattern (one concept
            # file per article, named after article id) — real compile emits
            # one file per UNIQUE concept across the whole KB.
            id_named = [p for p in concepts if p.stem.endswith("_concepts")]
            if id_named:
                errors.append(
                    f"{len(id_named)} concept files look like article-id stubs "
                    f"(e.g. '{id_named[0].name}'); real compile emits one file per "
                    "concept name, not per article. Likely LLM forgery — rerun compile."
                )
            for p in concepts:
                errors.extend(_check_concept(p))

    ci = kb / "vault" / "meta" / "concepts_index.json"
    if not ci.exists():
        errors.append("vault/meta/concepts_index.json missing (concept merge never ran)")
    else:
        try:
            idx = json.loads(ci.read_text(encoding="utf-8"))
            if not isinstance(idx, dict):
                errors.append(f"concepts_index.json must be a dict, got {type(idx).__name__}")
            elif not idx:
                errors.append("concepts_index.json is empty")
        except Exception as e:
            errors.append(f"concepts_index.json invalid JSON: {e}")

    staging = kb / "staging"
    if staging.exists():
        for status in ("pending", "processing"):
            p = staging / status
            if p.exists():
                leftovers = list(p.glob("*.json"))
                if leftovers:
                    errors.append(
                        f"staging/{status}/ has {len(leftovers)} unfinished task(s); "
                        f"compile did not complete (e.g. {leftovers[0].name})"
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
        print("usage: lcwiki compile-verify --kb KB_PATH", file=sys.stderr)
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1

    warnings: list[str] = []
    errors = verify(kb, warnings=warnings)
    if warnings:
        print(f"⚠️ compile verification — {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  WARN: {w}")
    if errors:
        print(f"❌ compile verification FAILED — {len(errors)} problem(s):")
        for e in errors:
            _fail(e)
        print(
            "\n⚠️ Do NOT hand-craft frontmatter / body sections. "
            "Rerun: lcwiki compile-prepare, then LLM generates article+concepts, "
            "then lcwiki compile-write per task."
        )
        return 1

    print("✅ compile verification passed — all articles + concepts have required schema.")
    return 0
