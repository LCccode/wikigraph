# Contributing to lcwiki

First off, thanks for taking an interest! lcwiki is a small opinionated tool; contributions that align with its three-layer architecture are most welcome.

## Ways to contribute

### 🐛 Bug reports
Open an issue with:
- lcwiki version (`lcwiki version`)
- Python version, OS
- Platform (Claude Code / OpenClaw / other)
- Minimal reproduction (a tiny .docx or .md that triggers the bug)
- What you expected vs what happened
- Full stacktrace if any

### 💡 Feature requests
Open an issue starting with `[idea]`. Explain:
- The problem you're trying to solve (not the feature you want)
- How it fits the three-layer architecture (article / concept / graph)
- Whether it belongs in lcwiki core or a companion project (e.g. lcwiki-web)

### 🔧 Pull requests

Before opening a PR:

1. **Open an issue first** if the change is non-trivial (anything >50 lines). Saves both of us time.
2. **Respect the CLI-first design**. Every user-facing capability must be a subcommand of `lcwiki` with atomic behavior, never a heredoc in skill.md.
3. **Run local smoke tests** before pushing:
   ```bash
   pip install -e ".[dev]"
   pytest tests/
   # Smoke against a tiny KB:
   mkdir -p /tmp/smoke_kb && lcwiki install --platform claude
   cp tests/fixtures/*.docx /tmp/smoke_kb/raw/inbox/
   lcwiki ingest-run --kb /tmp/smoke_kb
   lcwiki ingest-verify --kb /tmp/smoke_kb
   ```
4. **Update docs** if your PR changes user-facing behavior:
   - `skill.md` / `skill-claw.md` if AI-facing
   - `README.md` if user-facing
   - `CHANGELOG.md` always

## Architecture principles (please read before contributing)

lcwiki is built on four design principles that are **non-negotiable**:

### 1. Three-layer representation
Every output must fit into exactly one of: `article` (per-doc wiki page), `concept` (cross-doc concept node), or `graph` (edges + communities). Don't invent a fourth layer.

### 2. CLI-atomic commands
Every user-observable action is a `lcwiki <subcommand>` call. No heredoc-style Python scripts in skill.md. LLMs must invoke the CLI, not reimplement its logic. See `Execution Bounds` in `skill.md`.

### 3. Verify everything
After any write operation (ingest/compile/graph), there must be a corresponding `*-verify` command with a whitelist of allowed artifacts and filename conventions. If it doesn't verify, it didn't happen.

### 4. Honest token costs
Every command writes to `logs/cost.jsonl` with input/output token estimates. Never hide cost.

## Code style

- Follow existing style — no strict linter, but prefer clarity over cleverness.
- No comments explaining **what** code does (that's the code's job); comments should explain **why** a non-obvious decision was made.
- Raise clear errors; never silently swallow exceptions in user-facing paths.

## Commit messages

```
<type>(<scope>): <subject>

<body — why>

Co-Authored-By: Your Name <email>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `chore`.

Examples:
- `feat(compile): accept --single-task flag for re-compile`
- `fix(merge): preserve concept_kind when consolidating duplicates`

## Release process

Maintainers only. See `docs/RELEASE.md` (coming soon).

## Communication

- GitHub Issues for bugs / features
- GitHub Discussions for open-ended questions
- (Twitter/X DM open for quick chats with maintainer [@LCccode](https://github.com/LCccode))

## Code of Conduct

By participating, you agree to abide by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Thanks for helping make lcwiki better 🧠
