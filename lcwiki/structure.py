"""Zero-LLM document structure extraction.

Deterministically parses markdown content to extract headings, tables,
lists, metrics, and key terms. Produces structure.json for use by
the compile step as anchoring context.
"""

import re
from collections import Counter


def extract_structure(content: str) -> dict:
    """Extract structural elements from markdown content.

    Args:
        content: Markdown text (content.md after conversion).

    Returns:
        dict with keys: headings, tables, lists, metrics, key_terms
    """
    lines = content.split("\n")
    return {
        "headings": _extract_headings(lines),
        "tables": _extract_tables(lines),
        "lists": _extract_lists(lines),
        "metrics": _extract_metrics(content),
        "key_terms": _extract_key_terms(content),
    }


def _extract_headings(lines: list[str]) -> list[dict]:
    """Extract heading hierarchy with line numbers."""
    headings = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        # Count heading level
        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break
        if level == 0 or level > 6:
            continue
        title = stripped[level:].strip()
        if not title:
            continue
        headings.append({
            "level": level,
            "title": title,
            "line": i + 1,
        })
    return headings


def _extract_tables(lines: list[str]) -> list[dict]:
    """Detect markdown tables and extract column info."""
    tables = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # A table starts with | ... | and the next line is | --- | --- |
        if line.startswith("|") and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line.startswith("|") and "---" in next_line:
                # Found a table header + separator
                columns = [c.strip() for c in line.split("|") if c.strip()]
                # Count rows
                row_count = 0
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    row_count += 1
                    j += 1
                tables.append({
                    "line": i + 1,
                    "columns": columns,
                    "rows": row_count,
                })
                i = j
                continue
        i += 1
    return tables


def _extract_lists(lines: list[str]) -> list[dict]:
    """Detect markdown lists (ordered and unordered)."""
    lists = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Unordered list: starts with - or *
        if re.match(r"^[-*]\s+\S", line):
            start = i
            items = 0
            max_depth = 1
            while i < len(lines):
                raw = lines[i]
                stripped = raw.strip()
                if not re.match(r"^[-*]\s+\S", stripped) and stripped:
                    break
                if not stripped:
                    i += 1
                    continue
                items += 1
                indent = len(raw) - len(raw.lstrip())
                depth = indent // 2 + 1
                if depth > max_depth:
                    max_depth = depth
                i += 1
            if items > 0:
                lists.append({
                    "line": start + 1,
                    "type": "unordered",
                    "items": items,
                    "depth": max_depth,
                })
            continue
        # Ordered list: starts with 1. 2. etc
        if re.match(r"^\d+\.\s+\S", line):
            start = i
            items = 0
            while i < len(lines):
                stripped = lines[i].strip()
                if not re.match(r"^\d+\.\s+\S", stripped) and stripped:
                    break
                if not stripped:
                    i += 1
                    continue
                items += 1
                i += 1
            if items > 0:
                lists.append({
                    "line": start + 1,
                    "type": "ordered",
                    "items": items,
                    "depth": 1,
                })
            continue
        i += 1
    return lists


# Patterns for numeric metrics
_METRIC_PATTERNS = [
    # Percentages: 95%, ≥90%, ≤5%
    re.compile(r"[≥≤><]?\s*(\d+(?:\.\d+)?)\s*%"),
    # Currency: 599元, 100万, ¥500
    re.compile(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|万元|亿元|万|亿)"),
    # Counts with units: 30人, 5年, 12个, 4课时
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:人|年|个|台|课时|天|小时|分钟|所|间|套|册|节)"),
]


def _extract_metrics(content: str) -> list[dict]:
    """Extract numeric metrics (percentages, currency, counts with units)."""
    metrics = []
    seen = set()
    for line_num, line in enumerate(content.split("\n"), 1):
        for pattern in _METRIC_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0).strip()
                if value in seen:
                    continue
                seen.add(value)
                # Get surrounding context (±20 chars)
                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end].strip()
                metrics.append({
                    "value": value,
                    "context": context,
                    "line": line_num,
                })
    return metrics


# Chinese stopwords for term extraction
_STOPWORDS = set("的了是在有和与及等也都对为不到要这那就被从而但或如果可以一个人我你他她它们上下中大小多少")


def _extract_key_terms(content: str) -> list[str]:
    """Extract high-frequency key terms (Chinese + English)."""
    # Chinese terms: 2-6 character sequences
    cn_terms = re.findall(r"[\u4e00-\u9fff]{2,6}", content)
    # English terms: multi-word capitalized phrases or technical terms
    en_terms = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", content)
    # English acronyms/technical: AI, KPI, SOP, PBL etc
    acronyms = re.findall(r"\b[A-Z]{2,6}\b", content)

    # Count frequencies
    counter: Counter = Counter()
    for t in cn_terms:
        if len(t) >= 2 and not all(c in _STOPWORDS for c in t):
            counter[t] += 1
    for t in en_terms:
        counter[t] += 1
    for t in acronyms:
        if t not in ("MD", "PDF", "HTML", "HTTP", "URL", "API"):
            counter[t] += 1

    # Return top terms (frequency >= 2, up to 30)
    return [term for term, count in counter.most_common(30) if count >= 2]
