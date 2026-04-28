"""Wiki compilation helpers for LLM Wiki.

Manages the staging pipeline, context loading, frontmatter templates,
and risk assessment. The actual LLM compilation call is orchestrated
by skill.md — this module provides the supporting Python functions.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lcwiki.index import load_concepts_index, match_related_concepts


# --- Staging Pipeline ---

def create_task(sha256: str, raw_path: str, task_type: str = "compile_wiki") -> dict:
    """Create a compilation task descriptor."""
    return {
        "task_id": f"{sha256[:8]}_{task_type}",
        "type": task_type,
        "sha256": sha256,
        "raw_path": raw_path,
        "status": "pending",
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "finished_at": None,
        "attempts": 0,
        "max_attempts": 3,
        "error": None,
        "outputs": {
            "created_pages": [],
            "updated_pages": [],
        },
    }


def save_task(task: dict, staging_dir: Path) -> Path:
    """Write task.json to the appropriate staging subdirectory."""
    status = task.get("status", "pending")
    target_dir = staging_dir / status
    target_dir.mkdir(parents=True, exist_ok=True)
    task_path = target_dir / f"{task['task_id']}.json"
    task_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return task_path


def move_task(task: dict, staging_dir: Path, new_status: str) -> Path:
    """Move a task to a new status directory."""
    old_status = task["status"]
    old_path = staging_dir / old_status / f"{task['task_id']}.json"

    task["status"] = new_status
    task.setdefault("started_at", None)
    task.setdefault("finished_at", None)
    if new_status == "processing" and task["started_at"] is None:
        task["started_at"] = datetime.now(timezone.utc).isoformat()
    elif new_status in ("done", "failed"):
        task["finished_at"] = datetime.now(timezone.utc).isoformat()

    new_path = save_task(task, staging_dir)

    if old_path.exists() and old_path != new_path:
        old_path.unlink()

    return new_path


def list_tasks(staging_dir: Path, status: str = "pending") -> list[dict]:
    """List all tasks in a given status directory."""
    target_dir = staging_dir / status
    if not target_dir.exists():
        return []
    tasks = []
    for f in sorted(target_dir.glob("*.json")):
        try:
            tasks.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return tasks


# --- Context Loading (Token Optimization: Level 0/1/2) ---

def load_compile_context(
    task: dict,
    kb_root: Path,
    max_related_concepts: int = 5,
) -> dict:
    """Load the compilation context for a task using layered loading.

    Level 0: GRAPH_REPORT_SUMMARY (global overview, ~5K tokens)
    Level 1: concepts_index + matched related concepts (~10K tokens)
    Level 2: (handled by LLM via tool_use, not loaded here)

    Returns dict with keys: original_path, content_md, structure, level0_summary, level1_concepts, related_concept_names

    Design note (Option B): compile reads ORIGINAL file directly for full fidelity.
    content.md is only used for structure extraction and caching, not as primary compile input.
    """
    # Locate archive directory
    raw_path = Path(task["raw_path"])
    content_md = ""
    structure = {}
    original_path = ""

    content_path = kb_root / raw_path
    archive_dir = content_path.parent

    # Find original file (original.docx, original.doc, original.pdf, etc.)
    for f in archive_dir.glob("original.*"):
        original_path = str(f)
        break

    # Read content.md (used for structure extraction + fallback)
    if content_path.exists():
        content_md = content_path.read_text(encoding="utf-8", errors="replace")

    # Read structure.json
    structure_path = archive_dir / "structure.json"
    if structure_path.exists():
        try:
            structure = json.loads(structure_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Level 0: Global summary
    summary_path = kb_root / "vault" / "graph" / "GRAPH_REPORT_SUMMARY.md"
    level0_summary = ""
    if summary_path.exists():
        level0_summary = summary_path.read_text(encoding="utf-8", errors="replace")

    # Level 1: Related concepts via index + key_terms matching
    meta_dir = kb_root / "vault" / "meta"
    concepts_index = load_concepts_index(meta_dir)
    key_terms = structure.get("key_terms", [])
    key_terms_llm = structure.get("key_terms_llm", [])  # LLM-enriched terms (from previous compile backfill)
    related_names = match_related_concepts(
        key_terms, concepts_index, top_n=max_related_concepts,
        key_terms_llm=key_terms_llm,
    )

    # Read matched concept pages (first paragraph only to save tokens)
    level1_concepts = []
    for name in related_names:
        info = concepts_index.get(name, {})
        concept_path = kb_root / "vault" / "wiki" / info.get("path", "")
        if concept_path.exists():
            text = concept_path.read_text(encoding="utf-8", errors="replace")
            # Extract first paragraph (after frontmatter)
            lines = text.split("\n")
            first_para = ""
            in_frontmatter = False
            for line in lines:
                if line.strip() == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter:
                    continue
                if line.strip() and not line.startswith("#"):
                    first_para = line.strip()
                    break
            level1_concepts.append({
                "name": name,
                "summary": info.get("summary", first_para),
                "aliases": info.get("aliases", []),
                "article_count": info.get("article_count", 0),
            })

    return {
        "original_path": original_path,
        "content_md": content_md,
        "structure": structure,
        "level0_summary": level0_summary,
        "level1_concepts": level1_concepts,
        "related_concept_names": related_names,
    }


# --- Frontmatter Templates ---

ARTICLE_FRONTMATTER_TEMPLATE = """---
title: "{title}"
doc_type: {doc_type}
domain: {domain}
topic: {topic}
region: "{region}"
customer: "{customer}"
customer_type: "{customer_type}"
source_sha256: "{source_sha256}"
concepts: {concepts}
aliases: {aliases}
created_at: "{created_at}"
compiled_by: "{compiled_by}"
confidence: {confidence}
---"""
# 注意 aliases：本文档的别名/同义词列表（list[str]）。如无别名填空列表 []，
# 不得省略此字段（FIX-C / v0.6 起）。示例：["AI教学助手", "智能备课系统"]

DOC_TYPE_SECTIONS = {
    "solution": ["项目背景", "核心需求", "解决方案", "关键模块", "KPI 与指标", "报价结构", "时间线", "关联概念", "来源"],
    "manual": ["适用版本", "前置条件", "操作步骤", "故障码", "注意事项", "关联概念", "来源"],
    "faq": ["问题与答案", "关联概念", "来源"],
    "step": ["流程节点", "责任人", "输入", "输出", "注意事项", "关联概念", "来源"],
}


def generate_frontmatter(
    title: str,
    doc_type: str = "solution",
    domain: list[str] | None = None,
    topic: list[str] | None = None,
    region: str = "",
    customer: str = "",
    customer_type: str = "",
    source_sha256: str = "",
    concepts: list[str] | None = None,
    aliases: list[str] | None = None,
    compiled_by: str = "claude-opus-4-6",
    confidence: float = 0.9,
) -> str:
    """Generate YAML frontmatter for an article."""
    return ARTICLE_FRONTMATTER_TEMPLATE.format(
        title=title,
        doc_type=doc_type,
        domain=json.dumps(domain or ["业务"], ensure_ascii=False),
        topic=json.dumps(topic or [], ensure_ascii=False),
        region=region,
        customer=customer,
        customer_type=customer_type,
        source_sha256=source_sha256,
        concepts=json.dumps(concepts or [], ensure_ascii=False),
        aliases=json.dumps(aliases or [], ensure_ascii=False),
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        compiled_by=compiled_by,
        confidence=confidence,
    )


def get_section_template(doc_type: str) -> list[str]:
    """Get the section headings for a given doc_type."""
    return DOC_TYPE_SECTIONS.get(doc_type, DOC_TYPE_SECTIONS["solution"])


# --- Risk Assessment ---

def take_concepts_snapshot(meta_dir: Path) -> dict:
    """Take a snapshot of concepts_index BEFORE compile starts.

    This snapshot is used for risk assessment — new concepts are
    detected against the pre-compile state, not the live index
    that gets updated as each article is compiled.
    """
    from lcwiki.index import load_concepts_index
    return dict(load_concepts_index(meta_dir))


def assess_risk(
    article_concepts: list[str],
    existing_concepts: dict,
    confidence: float,
) -> str:
    """Assess whether an article should go to review or auto-publish.

    Returns 'review' or 'auto'.
    Rules from design doc:
    - New concept (not in existing_concepts) → review
    - confidence < 0.7 → review
    - Otherwise → auto

    IMPORTANT: existing_concepts should be a PRE-COMPILE SNAPSHOT,
    not the live index. Use take_concepts_snapshot() before compile starts.
    """
    # Check for new concepts
    for c in article_concepts:
        if c not in existing_concepts:
            return "review"

    # Low confidence
    if confidence < 0.7:
        return "review"

    return "auto"


# --- Wiki Index Management ---

def update_wiki_index(wiki_dir: Path, articles: list[dict] | None = None) -> None:
    """Regenerate vault/wiki/index.md from all articles.

    The index serves dual purpose: human browsing + Agent navigation.
    """
    articles_dir = wiki_dir / "articles"
    concepts_dir = wiki_dir / "concepts"

    # Count articles
    article_count = len(list(articles_dir.glob("*.md"))) if articles_dir.exists() else 0
    concept_count = len(list(concepts_dir.glob("*.md"))) if concepts_dir.exists() else 0

    lines = [
        "# LLM Wiki 知识库",
        "",
        f"> {article_count} 篇 article / {concept_count} 个 concept",
        "",
        "## 文章列表",
        "",
    ]

    if articles_dir.exists():
        for f in sorted(articles_dir.glob("*.md")):
            name = f.stem
            lines.append(f"- [[articles/{name}]]")

    lines.extend(["", "## 概念列表", ""])

    if concepts_dir.exists():
        for f in sorted(concepts_dir.glob("*.md")):
            name = f.stem
            lines.append(f"- [[concepts/{name}]]")

    index_path = wiki_dir / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines), encoding="utf-8")


# --- Directory Initialization ---

def init_kb(kb_root: Path) -> None:
    """Initialize the knowledge base directory structure."""
    dirs = [
        "raw/inbox",
        "raw/archive",
        "raw/failed",
        "staging/pending",
        "staging/processing",
        "staging/review",
        "staging/failed",
        "vault/wiki/articles",
        "vault/wiki/concepts",
        "vault/wiki/decisions",
        "vault/wiki/templates",
        "vault/graph/cache",
        "vault/queries/cache",
        "vault/queries/memory",
        "vault/meta",
        "logs",
    ]
    for d in dirs:
        (kb_root / d).mkdir(parents=True, exist_ok=True)

    # Create config.json if not exists
    config_path = kb_root / "config.json"
    if not config_path.exists():
        from lcwiki._default_config import DEFAULT_CONFIG
        config_path.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Create empty index.jsonl if not exists
    index_path = kb_root / "raw" / "index.jsonl"
    if not index_path.exists():
        index_path.touch()

    # Create initial wiki index
    update_wiki_index(kb_root / "vault" / "wiki")


# --- Logging ---

def log_compile(
    kb_root: Path,
    task_id: str,
    article_title: str,
    concepts_count: int,
    confidence: float,
    risk: str,
    input_chars: int,
    output_chars: int,
    took_seconds: float,
) -> None:
    """Log a compile operation to logs/compile.log and logs/cost.jsonl."""
    logs_dir = kb_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    # Estimate tokens: Chinese ~2 chars/token, English ~4 chars/token, average ~2.5
    est_input_tokens = int(input_chars / 2.5)
    est_output_tokens = int(output_chars / 2.5)

    # compile.log (human readable)
    log_line = (
        f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"COMPILE {task_id} | {article_title} | "
        f"{concepts_count} concepts | conf={confidence:.2f} | risk={risk} | "
        f"~{est_input_tokens} in + ~{est_output_tokens} out tokens | "
        f"{took_seconds:.1f}s\n"
    )
    with open(logs_dir / "compile.log", "a", encoding="utf-8") as f:
        f.write(log_line)

    # cost.jsonl (machine readable)
    cost_record = {
        "op": "compile",
        "task_id": task_id,
        "article": article_title,
        "at": now.isoformat(),
        "input_chars": input_chars,
        "output_chars": output_chars,
        "est_input_tokens": est_input_tokens,
        "est_output_tokens": est_output_tokens,
        "took_seconds": took_seconds,
        "confidence": confidence,
        "risk": risk,
    }
    with open(logs_dir / "cost.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(cost_record, ensure_ascii=False) + "\n")


# --- Frontmatter validation & templates (C1) ---

_ARTICLE_REQUIRED = {"title", "doc_type", "source_sha256", "concepts", "compiled_by", "tldr"}
_CONCEPT_REQUIRED = {"name", "aliases", "doc_type", "summary"}


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse leading '---\n...\n---\n' frontmatter. Returns (fm_dict, body).

    Uses a tolerant YAML-like parser (only top-level key: value or key: [list]).
    Raises ValueError if content does not start with '---'.
    """
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        raise ValueError("missing frontmatter: content must start with '---'")
    end = content.find("\n---\n", 4)
    if end < 0:
        end = content.find("\n---\r\n", 4)
        if end < 0:
            raise ValueError("missing frontmatter: no closing '---' found")
    block = content[4:end]
    body = content[end:].lstrip("\n-\r")
    fm: dict = {}
    for line in block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            fm[k] = [s.strip().strip('"').strip("'") for s in inner.split(",") if s.strip()] if inner else []
        else:
            fm[k] = v.strip('"').strip("'")
    return fm, body


def validate_article_frontmatter(content: str) -> dict:
    """Validate an article's frontmatter. Returns parsed fm dict or raises ValueError.

    Enforces only the lcwiki-core universal fields. Domain-specific fields
    (region/customer/customer_type/etc.) are optional — each deployment or
    downstream skill can add its own validator on top without modifying core.
    doc_type is required but not enumerated: any non-empty string is allowed
    so the skill can be used across domains (software docs, research notes,
    policy libraries, etc.).
    """
    fm, _ = _parse_frontmatter(content)
    missing = _ARTICLE_REQUIRED - set(fm.keys())
    if missing:
        raise ValueError(f"article frontmatter missing fields: {sorted(missing)}")
    if not fm.get("title"):
        raise ValueError("article frontmatter 'title' is empty")
    if not fm.get("doc_type"):
        raise ValueError("article frontmatter 'doc_type' is empty")
    return fm


def validate_concept_frontmatter(content: str) -> dict:
    """Validate a concept's frontmatter. Returns parsed fm dict or raises ValueError."""
    fm, _ = _parse_frontmatter(content)
    missing = _CONCEPT_REQUIRED - set(fm.keys())
    if missing:
        raise ValueError(f"concept frontmatter missing fields: {sorted(missing)}")
    if fm.get("doc_type") != "concept":
        raise ValueError(f"concept doc_type must be 'concept', got: {fm.get('doc_type')}")
    return fm


def _yaml_list(items: list[str]) -> str:
    """Render a list as YAML inline array, escaping quotes."""
    return "[" + ", ".join(f'"{s}"' for s in items) + "]"


_CONCEPT_KINDS = {
    "capability", "product", "module", "framework",
    "policy", "metric", "role", "method", "other",
}


def build_concept_markdown(
    cname: str,
    summary: str,
    aliases: list[str] | None = None,
    article_title: str | None = None,
    domain: list[str] | None = None,
    concept_kind: str = "other",
    body_sections: dict[str, str] | None = None,
) -> str:
    """Render a new concept file's full text with frontmatter.

    Args:
        concept_kind: one of capability/product/module/framework/policy/metric/
            role/method/other. Used by god_nodes/query filters to separate
            "core abilities" from "policy references" from "concrete products".
        body_sections: dict of {section_heading: section_content}. Populates
            the "## 概要 / ## 关键特征 / ## 在方案中的应用 / ## 相关概念" body.
            If not provided, falls back to the old thin-stub form (summary only).
    """
    from datetime import date
    today = date.today().isoformat()
    aliases = aliases or []
    domain = domain or []
    if concept_kind not in _CONCEPT_KINDS:
        concept_kind = "other"

    fm_lines = [
        "---",
        f'name: "{cname}"',
        f"aliases: {_yaml_list(aliases)}",
        f'summary: "{summary}"',
        f"domain: {_yaml_list(domain)}",
        'doc_type: "concept"',
        f'concept_kind: "{concept_kind}"',
        "article_count: 1",
        f'created_at: "{today}"',
        f'updated_at: "{today}"',
        "---",
    ]
    body = [f"# {cname}", ""]
    if body_sections:
        for heading, content in body_sections.items():
            body += [f"## {heading}", "", content.strip(), ""]
    else:
        body += [summary, ""]
    if article_title and not (body_sections and "相关文章" in body_sections):
        body += ["## 相关文章", f"- [[{article_title}]]", ""]
    return "\n".join(fm_lines + [""] + body)


def update_concept_markdown(existing_text: str, article_title: str) -> str:
    """Append '- [[article_title]]' under '## 相关文章' if not already present.

    Preserves frontmatter. If the file has no frontmatter (legacy), wraps
    it in a minimal one on first touch — but normally a C2 backfill pass
    should have already added frontmatter.
    """
    if article_title in existing_text:
        return existing_text
    if "## 相关文章" in existing_text:
        return existing_text.rstrip() + f"\n- [[{article_title}]]\n"
    return existing_text.rstrip() + f"\n\n## 相关文章\n- [[{article_title}]]\n"
