# Changelog

All notable changes to lcwiki will be documented in this file. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [Semantic Versioning](https://semver.org/).

## [0.5.0] — 2026-04-19

### Added
- **First public release.** Open-sourced under MIT as `github.com/LCccode/wikigraph`. Published to PyPI as `lcwiki`.
- README overhaul: three-layer architecture explained, comparison table vs graphify / LangChain / LlamaIndex, honest cost ballparks, Karpathy `/raw`-folder framing.
- Repository scaffolding: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE` (MIT), issue + PR templates, CI (`pytest`, `twine check`, `ruff`), PyPI trusted-publishing workflow.
- Smoke tests: `test_package_imports`, `test_core_modules_import`, `test_cli_version`.

### Notes
- All internal code paths, CLI commands, skill names, and imports remain `lcwiki`. Only the GitHub repository name is `wikigraph`. `pip install lcwiki` is unchanged.
- Private data scrubbed from all shipped files: no local paths, no real customer names, no internal IPs, no test-data specifics.

## [0.4.1] — 2026-04-19

### Fixed
- **Critical** — `lcwiki install --platform claw` was writing SKILL.md to `~/.openclaw/skills/lcwiki/` but OpenClaw actually reads from `~/.openclaw/workspace/skills/`. All OpenClaw deployments since 0.1.0 were silently broken (agent couldn't read skill, fell back to guessing). Fixed in `_PLATFORM_CONFIG["claw"]["skill_dst"]`.
- `consolidate_by_source_file` now accepts `kb_root` kwarg and auto-heals `source_file` without prefix (`XXX.md` → `concepts/XXX.md` or `articles/XXX.md`) and fixes `file_type` mismatches against the actual directory on disk.

### Added
- `server-install.sh` auto-installs two wrappers: `/usr/local/bin/lcwiki` → anaconda `lcwiki`, `/usr/local/bin/python3` → anaconda `python3`. Fixes the common "OpenClaw PATH doesn't include anaconda" bug where `import lcwiki` fails with `ModuleNotFoundError` in agent-side Python heredocs.
- `scripts/deploy.sh` — one-command remote deploy (SSH + auto-verify under simulated agent env).
- `docs/DEPLOY.md` — complete new-server deployment guide (beginner-friendly, all absolute paths, offline / air-gapped options).

## [0.4.0] — 2026-04-18

### Changed
- Skill execution now **requires subagent dispatch** for any KB with > 3 files (compile) or > 5 files (graph Step 2). Previous "sequential mode" was too easy for OpenClaw agent to truncate under context pressure. Chunk size 5-8 for compile, 10-15 for graph.
- Subagent prompts now **inline all hard schema rules** (node shape, source_file prefix, relation whitelist, hyperedge member format) instead of saying "see parent skill". OpenClaw agent was shortcutting the reference.

## [0.3.1] — 2026-04-18

### Fixed
- Skill installation path bug (see 0.4.1 for complete fix — 0.3.1 was an incomplete attempt).

## [0.3.0] — 2026-04-18

### Added
- **ingest-run** / **ingest-verify** — atomic CLI for smart-ingest (new/updated/skipped/failed classification), replacing the previous 40-line Python heredoc in skill.md.
- **compile-prepare** / **compile-write** / **compile-verify** — three-phase CLI for compile:
  - `prepare`: take concept snapshot + list tasks (determinist)
  - `write`: validate + write article/concepts (determinist)
  - `verify`: schema check (9 concept_kinds, 4 body sections, ≥3 concepts/article, tldr length, etc.)
  - LLM only runs between prepare and write; no more Python heredoc handoff.
- **Execution Bounds** section at top of skill.md/skill-claw.md — six hard rules (CLI owns determinism / no Bash means STOP / whitelist / verify is ground truth / no silent success / etc.)

### Changed
- `graph-run` is now fully atomic (previously 150-line heredoc in skill.md). Agent just invokes `lcwiki graph-run --kb KB --extraction FILE.json`.
- `graph-verify` validates: files whitelist under `vault/graph/`, valid relation set, non-empty node count, nav filename sanity (catches `![img-003](...).md` corruption).

### Removed
- All `python3 << 'EOF' ... EOF` heredoc-style logic has been excised from skill.md. LLMs now MUST invoke CLI — there is no fallback path that uses Python source.

## [0.2.0] — 2026-04-18

### Added
- Auto-install skill on server (`lcwiki install --platform claw`).
- `convert.py` LibreOffice integration for legacy `.doc` / `.ppt` formats (graceful degrade if `soffice` not on PATH).
- `ingest.py` smart-ingest with three-way classification: `skipped` (sha match + already compiled) → delete from inbox; `updated` (same filename stem, different sha) → soft-delete old to `.trash/` + ingest new; `new` → standard path.

### Changed
- `lcwiki update <filename>` now complements smart ingest — it's for the case where the user wants to drop an existing record without uploading a replacement.

## [0.1.0] — 2026-04-17

### Added
- Initial release.
- Three-layer architecture: articles (per-doc wiki) + concepts (cross-doc, 4-section body + aliases) + graph (directed, hyperedges, communities).
- `vendored graphify` at `lcwiki/_vendored_graphify/` for build/cluster/analyze/export algorithms (MIT-licensed, reused).
- Six subcommands: `ingest` / `compile` / `graph` / `audit` / `query` / `update` / `status`.
- `concept_kind` enum: `capability / product / module / framework / policy / metric / role / method / other`.
- Family merge by aliases: concepts_index.json prevents duplicate entries.
- `tldr` field in article frontmatter (≤100 char WHO/WHAT/HOW/KPI summary for query-layer token savings).
- KPI drill-down: article-level numbers sink into concept `关键特征` section for direct concept-page answering.

[0.4.1]: https://github.com/LCccode/wikigraph/releases/tag/v0.4.1
[0.4.0]: https://github.com/LCccode/wikigraph/releases/tag/v0.4.0
[0.3.1]: https://github.com/LCccode/wikigraph/releases/tag/v0.3.1
[0.3.0]: https://github.com/LCccode/wikigraph/releases/tag/v0.3.0
[0.2.0]: https://github.com/LCccode/wikigraph/releases/tag/v0.2.0
[0.1.0]: https://github.com/LCccode/wikigraph/releases/tag/v0.1.0
