"""Tests for FIX-C: aliases 字段 verify 检查。

Test 名称严格对照架构方案 §4.9 用例清单（验证相关 3 个）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lcwiki.compile_verify import _check_article


# 一个含必填字段且 body 充足的 article 模板（用于 verify 测试）
_BASE_BODY = "## 核心摘要\n\n" + ("这是核心摘要内容。" * 30) + "\n\n## 详细内容\n\n" + ("详细内容大段文字。" * 30) + "\n"


def _write_article(
    path: Path,
    aliases_line: str | None,
    *,
    title: str = "Test Article",
    sha: str = "abc123def456",
) -> None:
    """写一个最小满足其他必填字段的 article。aliases_line 控制 aliases 字段格式。"""
    fm_lines = [
        "---",
        f'title: "{title}"',
        "doc_type: solution",
        f'source_sha256: "{sha}"',
        'concepts: ["A", "B", "C"]',
        'compiled_by: "test"',
        "confidence: 0.9",
        'tldr: "this is a sufficiently long tldr for the article"',
    ]
    if aliases_line is not None:
        fm_lines.append(aliases_line)
    fm_lines.append("---")
    content = "\n".join(fm_lines) + "\n" + _BASE_BODY
    path.write_text(content, encoding="utf-8")


def test_aliases_field_missing_warn_not_error(tmp_path: Path, monkeypatch) -> None:
    """旧 article 无 aliases 字段，verify 报 warning（默认非严格模式）"""
    monkeypatch.delenv("LCWIKI_STRICT_ALIASES", raising=False)
    p = tmp_path / "old.md"
    _write_article(p, aliases_line=None)

    warnings: list[str] = []
    errs = _check_article(p, warnings=warnings)
    # 不应进 errs
    assert all("aliases" not in e for e in errs), f"errs={errs}"
    # 应该有一条 warn 提到 aliases 缺失
    assert any("aliases" in w and "缺失" in w for w in warnings), f"warnings={warnings}"


def test_aliases_field_empty_list_ok(tmp_path: Path, monkeypatch) -> None:
    """aliases: [] 验证通过（无 errs 也无 warn）"""
    monkeypatch.delenv("LCWIKI_STRICT_ALIASES", raising=False)
    p = tmp_path / "empty.md"
    _write_article(p, aliases_line="aliases: []")

    warnings: list[str] = []
    errs = _check_article(p, warnings=warnings)
    assert all("aliases" not in e for e in errs), f"errs={errs}"
    assert all("aliases" not in w for w in warnings), f"warnings={warnings}"


def test_aliases_field_non_list_error(tmp_path: Path, monkeypatch) -> None:
    """aliases: "xxx" 报 error"""
    monkeypatch.delenv("LCWIKI_STRICT_ALIASES", raising=False)
    p = tmp_path / "bad.md"
    # 注意：当前 _parse_frontmatter 会把这种值解析为 str
    _write_article(p, aliases_line='aliases: "just-a-string"')

    warnings: list[str] = []
    errs = _check_article(p, warnings=warnings)
    # 应该有 errs 提到 aliases 类型错误
    assert any("aliases" in e and "list" in e for e in errs), f"errs={errs}"
