# lcwiki

[English](README.md) | [简体中文](README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/lcwiki.svg)](https://pypi.org/project/lcwiki/)
[![Python](https://img.shields.io/pypi/pyversions/lcwiki.svg)](https://pypi.org/project/lcwiki/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![CI](https://github.com/LCccode/wikigraph/actions/workflows/ci.yml/badge.svg)](https://github.com/LCccode/wikigraph/actions/workflows/ci.yml)

**A drop-in wiki-builder skill for AI coding assistants.** Type `/lcwiki` in Claude Code or OpenClaw — it reads any folder of docs, compiles them into a structured wiki + knowledge graph, and lets your AI answer questions from that wiki at **~10% the token cost of vanilla RAG**.

Fully multimodal. Drop in `.docx`, `.pdf`, `.xlsx`, `.pptx`, markdown, images, audio, or video — lcwiki converts everything to markdown, extracts per-doc structure, concepts with family aliases, and a vis-network knowledge graph in one shot. Then it lets your AI query the wiki with a three-layer token-first fallback: scan 100-token tldrs → fall back to article body → only touch raw content as a last resort.

> **Inspired by Andrej Karpathy's `/raw` folder idea** — the one he talks about on podcasts, where he drops papers, screenshots, tweets, and whiteboard photos into a single directory and wants his AI to just *understand it all*. [safishamsi/graphify](https://github.com/safishamsi/graphify) turned that folder into a knowledge graph. **lcwiki takes it one layer further: it turns your `/raw` folder into a proper wiki *and* a graph — so your AI has both long-term memory *and* a map**. Every doc gets a structured article with a 100-token tldr for cheap lookups; every concept gets a standalone page with family aliases; every connection lives in a persistent queryable graph. All three layers are built in one shot by a Claude subagent pass, wrapped with CLI-atomic write-verify so your agent can't silently corrupt the data, and maintained long-term by a self-healing `/lcwiki audit` with LLM-as-judge checks.

```
/lcwiki ingest      # drop anything into raw/inbox/, convert + stage
/lcwiki compile     # LLM reads each doc → structured articles + concepts
/lcwiki graph       # build knowledge graph → graph.html
/lcwiki query "what's the budget of project X?"
```

```
vault/
├── wiki/
│   ├── articles/*.md     per-doc wiki pages with YAML frontmatter + 100-token tldr
│   └── concepts/*.md     standalone concept pages with 4-section body + aliases
├── graph/
│   ├── graph.html        interactive vis-network graph — click nodes, jump to source
│   ├── graph.json        persistent graph — query weeks later without re-reading
│   └── GRAPH_REPORT.md   god nodes, surprising connections, audit findings
└── meta/
    ├── concepts_index.json   concept aliases → canonical name
    └── source_map.json       sha256 → raw file → generated articles
```

Add a `.lcwikiignore` to skip folders:

```
# .lcwikiignore
_archive/
drafts/
*.generated.md
```

## Why three layers

Traditional vector RAG fails on structured content (proposals, contracts, research reports): chunks break tables across boundaries, embedding recall is noisy on domain-specific terms, and every query re-reads the same chunks and burns tokens summarizing the same prose forever.

lcwiki's fix: **read each doc once with an LLM, write a proper wiki, query the wiki.**

| Layer | Size | Query pattern |
|---|---|---|
| **1. Article** (`articles/*.md`) | 3–8 KB per doc | "Tell me about this doc" |
| **2. Concept** (`concepts/*.md`) | 1–2 KB per concept | "What is X?" across docs |
| **3. Graph** (`graph/*.json`) | — | "How are these connected?" |

Every query uses a **token-first fallback**: scan every article's ~100-token `tldr` first (usually <5K total for a whole KB), open the matching article body only if needed (3K), touch raw content only as a last resort. On real proposal-style corpora, this cuts per-query token cost by **~80% vs vanilla RAG** while matching or beating accuracy on factual questions like "what's the budget of Project X".

## How it works

lcwiki runs three passes.

**First** (`ingest`), a deterministic Python pass converts every file in `raw/inbox/` to markdown (docx via python-docx, pdf via pypdf, xlsx via openpyxl, pptx/images/video optional), extracts basic structure (headings, tables, entities) with zero LLM cost, classifies each file as `new` / `updated` (same filename, new sha → auto-cleanup old) / `skipped` / `failed`, and stages each into `staging/pending/`. Images are kept inline. Nothing burns tokens yet.

**Second** (`compile`), an LLM subagent reads every staged `content.md` and produces a structured wiki article (YAML frontmatter with `tldr`, `doc_type`, `concepts`, `source_sha256`, `confidence` — and a body that preserves every table, every list item, every data point from the source, not a summary). Concepts are extracted as standalone pages with 4-section bodies (概要 / 关键特征 / 在方案中的应用 / 相关概念) and family aliases — "Digital Learning Platform" and "digital-learning-platform" auto-merge to one canonical concept. Every write goes through `lcwiki compile-write` with a whitelist-schema `compile-verify` — agents can't invent frontmatter fields; the verify command rejects anything outside the schema.

**Third** (`graph`), an LLM subagent reads the compiled wiki and emits nodes (documents + concepts), edges (tagged `EXTRACTED` / `INFERRED` / `AMBIGUOUS` with confidence scores — never a default 0.5), and hyperedges (3+ node groupings). The results go through `lcwiki graph-run`, which builds a NetworkX directed graph, runs Leiden community detection for coloring, and exports interactive `graph.html` + persistent `graph.json` + plain-language `GRAPH_REPORT.md`. Every edge is marked `EXTRACTED` (found directly in source), `INFERRED` (reasonable inference with confidence), or `AMBIGUOUS` (flagged for review). You always know what was found vs guessed.

## Query, and `/lcwiki audit`

`/lcwiki query "what's the budget of project X?"` runs the three-layer fallback: it first scans every article's `tldr` field (cheap — ~100 tokens each), opens only the matching article's body if tldrs are insufficient, and only falls through to the raw content.md as a last resort. Token cost per query: **~100–3000** vs 5K–20K+ for vanilla RAG on the same questions.

`/lcwiki audit` catches the rot that accumulates as you compile more docs: ghost nodes (nodes with no edges), orphan concepts (concepts referenced by nothing), missing source files, edges below confidence threshold. It uses an LLM-as-judge for the subjective calls and **always asks for user confirmation before deleting anything**. Every edit is logged, every graph change is backed up. The graph stays coherent long after your 50th `/lcwiki compile`.

## Install

**Requires:** Python 3.11+ and one of: [Claude Code](https://claude.ai/code), [OpenClaw](https://openclaw.com).

```bash
pip install lcwiki
lcwiki install --platform claude   # or --platform claw
```

Then drop some docs and go:

```bash
mkdir -p ~/.claude/lcwiki/raw/inbox
cp *.docx *.pdf ~/.claude/lcwiki/raw/inbox/
# In Claude Code:
/lcwiki ingest
/lcwiki compile
/lcwiki graph
/lcwiki query "what's the budget of project X?"
```

Open `~/.claude/lcwiki/vault/graph/graph.html` in a browser to explore the graph — click any node to jump to its wiki article.

### Optional extras

```bash
pip install 'lcwiki[leiden]'   # faster community detection (Python < 3.13)
pip install 'lcwiki[pptx]'     # PowerPoint ingestion
pip install 'lcwiki[video]'    # audio/video transcription via faster-whisper
pip install 'lcwiki[mcp]'      # Model Context Protocol server
pip install 'lcwiki[all]'      # everything
```

## How much does it cost

On a test corpus of a few dozen proposal-style docs (~1–3 MB total):

| | Cost | Notes |
|---|---|---|
| **Compile once** | ~$2 (one-time) | per dozen docs, with `qwen-plus` or `claude-sonnet` |
| **Query** | ~$0.01 each | tracked in `logs/cost.jsonl`; most queries stop at the tldr layer |
| **Audit** | ~$0.05 | full-graph health check, run weekly |

Actual numbers vary by model, doc complexity, and corpus size — the numbers above are ballpark from internal tests. Your mileage will vary.

The first `compile` is by far the heaviest step. After that, queries are cheap enough to run in tight loops — your AI assistant can check the wiki dozens of times per conversation without thinking about cost.

## Built for AI agents, not humans

Every user-facing operation is an **atomic CLI subcommand** that the agent invokes. The LLM never writes Python or directly edits JSON state — it calls `lcwiki compile-write`, `lcwiki graph-run`, `lcwiki audit`, and so on. Every write command has a matching `*-verify` with a **whitelist schema**: agents cannot invent frontmatter fields, cannot skip required concepts, cannot emit edges below the confidence floor. When agents try to shortcut the process (regex-scanning instead of actually reading the doc), the verify command rejects the output and forces a re-read.

This sounds over-engineered. It isn't. Agents cut corners constantly in ways that silently destroy your graph. The verify-gate is the only thing that made lcwiki's outputs reliable enough to trust.

## How it compares

|                                 | **lcwiki**            | graphify           | LangChain / LlamaIndex |
|---------------------------------|-----------------------|--------------------|-----------------------|
| Primary output                  | **wiki + graph**      | graph only         | retrieval pipeline     |
| Per-doc structured article      | **yes**               | no                 | no (chunks only)       |
| Concept as standalone page      | **yes** (4-section)   | no (just label)    | no                     |
| Knowledge graph                 | yes                   | yes                | optional               |
| Token cost per query            | **~100–3K**           | n/a                | 5K–20K+               |
| Agent-friendly CLI + verify gate| **yes**               | yes                | no (framework)         |
| Self-healing audit              | **yes** (LLM-judge)   | no                 | no                     |
| Works with Claude Code          | yes                   | yes                | yes                    |
| Works with OpenClaw             | **yes** (out of box)  | yes                | yes                    |
| MIT license                     | yes                   | yes                | yes                    |

lcwiki is **not** a replacement for LangChain or LlamaIndex — it's a pre-step. You can absolutely point a LangChain pipeline at lcwiki's compiled wiki. Most people won't need to: the `tldr + article` layer answers 80% of real questions directly, and you can ship a useful AI assistant on it alone.

## What's inside

```
lcwiki/
├── ingest.py           raw file → content.md + structure.json (zero LLM)
├── detect.py           file classification + sha256 dedup
├── convert.py          docx/pdf/xlsx/pptx → markdown
├── structure.py        headings, tables, key terms (zero LLM)
├── compile.py          LLM-driven article + concept generation (with validation)
├── compile_verify.py   whitelist-schema gate for `compile-write`
├── merge.py            concept family merging, source_file auto-heal
├── graph_cmd.py        build graph from LLM extraction
├── graph_verify.py     whitelist-schema gate for `graph-run`
├── audit.py            ghost-node / orphan-concept health check
├── query.py            three-layer token-first retrieval
├── backfill.py         retroactively enrich structure.json with LLM terms
├── _vendored_graphify/ networkx build + leiden clustering + vis-network export
└── skill*.md           agent-runtime skill definitions (Claude Code, OpenClaw)
```

The `_vendored_graphify/` subpackage is [safishamsi/graphify](https://github.com/safishamsi/graphify) (MIT), vendored rather than pip-depended so end users get a single `pip install` with no surprises.

## Roadmap

- [x] v0.5 — initial public release, three-layer query, audit, subagent-parallel compile
- [ ] v0.6 — `compile-write-direct` (bypass agent, call LLM API directly for cheaper batch compile)
- [ ] v0.7 — web admin UI (separate repo `lcwiki-web`)
- [ ] v0.8 — multi-user support, RBAC
- [ ] v1.0 — stable API, long-form doc refinement

See [CHANGELOG.md](./CHANGELOG.md) for detailed history.

## FAQ

**How is this different from LangChain / LlamaIndex?** Those are retrieval pipelines. lcwiki is a wiki-builder — a pre-step. You can (and some people will want to) stack a LangChain retriever on top of lcwiki's compiled wiki. Most don't need to.

**Why three layers instead of two?** We tried two (concept + graph). It couldn't answer per-doc questions like "what's the budget of Project X" because concepts are cross-doc by definition. The article layer is load-bearing.

**Does my AI need to remember all the `/lcwiki` commands?** No — that's the whole point of the atomic-CLI design. The skill file tells the AI the commands once; the AI just invokes them by name. `lcwiki compile-write --kb ... --task-id ... --article ...` is what an agent can learn; `ad-hoc Python that writes frontmatter YAML` is what an agent keeps screwing up.

**Can I run compile offline?** `ingest`, `graph`, and `audit` are pure-Python, fully offline. Only `compile` needs an LLM — it runs inside Claude Code / OpenClaw, which you point at whatever provider you want (Anthropic, OpenAI, Qwen, a local Ollama model, etc.).

**What about bigger corpora?** Tested on 42-doc corpora so far. Bigger should work — compile parallelizes with subagents (Claude Code) or runs sequentially (OpenClaw). If you hit a wall, file an issue with your doc count and format mix.

**Why does this exist?** Originally written out of frustration with vector RAG on structured docs. Proposals, contracts, and research reports have critical data points (budgets, dates, KPIs) buried inside tables — and chunking breaks tables. We wanted AI assistants to read each doc once, write a wiki, and answer from that wiki. The wiki is cheaper, more accurate on factual questions, and persistent across sessions.

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the non-negotiable architecture principles: three-layer, CLI-atomic, verify everything, honest cost numbers.

[github.com/LCccode/wikigraph/issues](https://github.com/LCccode/wikigraph/issues)

## License

[MIT](./LICENSE). Vendored `_vendored_graphify/` is also MIT, originally by [safishamsi/graphify](https://github.com/safishamsi/graphify).

## Acknowledgments

- [safishamsi/graphify](https://github.com/safishamsi/graphify) for the graph algorithms and the "graph of your raw folder" idea
- [vis-network](https://visjs.github.io/vis-network/) for the interactive graph renderer
- [Anthropic Claude Code](https://claude.ai/code) for the agent runtime that made the atomic-CLI design possible
- Everyone who filed real issues on the first buggy versions

---

Made by [@LCccode](https://github.com/LCccode). If lcwiki helps your team, a ⭐ on the repo is the nicest way to say thanks.
