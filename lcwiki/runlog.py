"""Unified run logging for lcwiki commands.

Every lcwiki command (ingest / compile / graph / audit / query) calls
`record_run()` when it finishes. The record captures command metadata,
per-command stats, token usage, schema warnings, and health indicators.

Outputs (under `<kb>/logs/`):
    run.jsonl                 append-only, one JSON line per run
    latest_run.md             human-readable report of the most recent run
    reports/<cmd>_<ts>.md     archived copy of each report

Design notes:
- Domain-agnostic: the `stats` and `tokens` dicts are free-form; each
  command fills what makes sense. No field is required.
- Non-destructive: failure to write the report never raises — we catch and
  ignore IO errors to avoid disrupting the main command.
- `tokens.breakdown` can optionally list per-subagent tokens so long runs
  (e.g. 6 subagent graph extractions) can be inspected.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


_STATUS_EMOJI = {"success": "✅", "partial": "⚠️", "error": "❌"}


def record_run(
    kb: Path,
    command: str,
    *,
    started_at: float,
    params: dict | None = None,
    stats: dict | None = None,
    tokens: dict | None = None,
    warnings: list[str] | None = None,
    status: str = "success",
) -> Path | None:
    """Write a run record. Returns the archived report path, or None on IO error."""
    ended_at = time.time()
    now = datetime.now(timezone.utc)
    rec = {
        "command": command,
        "status": status,
        "started_at": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(),
        "finished_at": now.isoformat(),
        "took_seconds": round(ended_at - started_at, 2),
        "params": params or {},
        "stats": stats or {},
        "tokens": tokens or {},
        "warnings": warnings or [],
    }

    try:
        logs_dir = kb / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with open(logs_dir / "run.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        md = render_report_md(rec)
        (logs_dir / "latest_run.md").write_text(md, encoding="utf-8")

        archive_dir = logs_dir / "reports"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{command}_{now.strftime('%Y%m%d_%H%M%S')}.md"
        archive_path.write_text(md, encoding="utf-8")
        return archive_path
    except OSError:
        return None


def render_report_md(rec: dict) -> str:
    """Render a human-readable markdown report from a run record."""
    status_emoji = _STATUS_EMOJI.get(rec.get("status", ""), "•")
    lines = [
        f"# lcwiki 运行报告 — `{rec['command']}`",
        "",
        f"- **状态**：{status_emoji} {rec.get('status', '')}",
        f"- **开始**：{rec.get('started_at', '')}",
        f"- **结束**：{rec.get('finished_at', '')}",
        f"- **耗时**：{rec.get('took_seconds', 0)}s",
    ]

    params = rec.get("params") or {}
    if params:
        lines += ["", "## 参数", ""]
        for k, v in params.items():
            lines.append(f"- `{k}`: `{v}`")

    stats = rec.get("stats") or {}
    if stats:
        lines += ["", "## 统计 / 健康指标", ""]
        lines.extend(_render_kv(stats))

    tokens = rec.get("tokens") or {}
    if tokens:
        lines += ["", "## Token 消耗", ""]
        it = int(tokens.get("input_tokens") or 0)
        ot = int(tokens.get("output_tokens") or 0)
        lines.append(f"- 输入：{it:,}")
        lines.append(f"- 输出：{ot:,}")
        lines.append(f"- **总计**：{(it + ot):,}")
        breakdown = tokens.get("breakdown")
        if breakdown:
            lines += ["", "### 分项"]
            for k, v in breakdown.items():
                if isinstance(v, dict):
                    vi = int(v.get("input_tokens") or 0)
                    vo = int(v.get("output_tokens") or 0)
                    lines.append(f"- {k}: in={vi:,} out={vo:,} total={(vi + vo):,}")
                else:
                    lines.append(f"- {k}: {v:,}")

    warnings = rec.get("warnings") or []
    if warnings:
        lines += ["", f"## 警告（{len(warnings)}）", ""]
        for w in warnings[:20]:
            lines.append(f"- ⚠️ {w}")
        if len(warnings) > 20:
            lines.append(f"- ... 还有 {len(warnings) - 20} 条")

    return "\n".join(lines) + "\n"


def _render_kv(d: dict, depth: int = 0) -> list[str]:
    """Render a possibly-nested dict as bullet list."""
    lines = []
    indent = "  " * depth
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{indent}- **{k}**：")
            lines.extend(_render_kv(v, depth + 1))
        elif isinstance(v, list):
            if not v:
                continue
            if all(isinstance(x, (str, int, float)) for x in v[:3]):
                lines.append(f"{indent}- **{k}**：{', '.join(str(x) for x in v[:10])}{' ...' if len(v) > 10 else ''}")
            else:
                lines.append(f"{indent}- **{k}**：({len(v)} items)")
        else:
            lines.append(f"{indent}- **{k}**：{v}")
    return lines


def tail_recent_runs(kb: Path, n: int = 10) -> list[dict]:
    """Load the last N records from run.jsonl (latest first). Safe if missing."""
    p = kb / "logs" / "run.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(records) >= n:
            break
    return records
