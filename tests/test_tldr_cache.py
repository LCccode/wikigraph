"""Tests for FIX-E: TldrCache 进程级缓存。

Test 名称严格对照架构方案 §6.5 用例清单。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest

from lcwiki.query import TldrCache, read_article_tldrs


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前重置单例缓存。"""
    TldrCache.reset()
    yield
    TldrCache.reset()


def _make_article(dir_path: Path, name: str, tldr: str) -> Path:
    """构造一篇含 tldr 的 article 文件。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    p = dir_path / f"{name}.md"
    content = f"""---
title: "{name}"
tldr: "{tldr}"
---

正文内容这里。
"""
    p.write_text(content, encoding="utf-8")
    return p


def test_tldr_cache_hit_no_disk_read(tmp_path: Path):
    """第二次 get 同一文件不触发 open（mock Path.read_text 计数）。"""
    p = _make_article(tmp_path, "doc1", "summary one")
    cache = TldrCache.instance()

    real_read_text = Path.read_text
    call_count = {"n": 0}

    def _counted_read_text(self, *a, **kw):
        call_count["n"] += 1
        return real_read_text(self, *a, **kw)

    with patch.object(Path, "read_text", _counted_read_text):
        first = cache.get(p)
        second = cache.get(p)
    assert first == "summary one"
    assert second == "summary one"
    # 第一次读 + 第二次命中缓存：read_text 只被调用 1 次
    assert call_count["n"] == 1


def test_tldr_cache_miss_on_mtime_change(tmp_path: Path):
    """文件 mtime 变化后重新读取。"""
    p = _make_article(tmp_path, "doc2", "version one")
    cache = TldrCache.instance()
    assert cache.get(p) == "version one"

    # 修改文件并调整 mtime，使其与缓存不同
    p.write_text(
        '---\ntitle: "doc2"\ntldr: "version two"\n---\n\nbody',
        encoding="utf-8",
    )
    # 显式推进 mtime 以保险（在某些 fs 上 write 可能不立刻改 mtime_ns）
    new_t = time.time() + 5
    os.utime(p, (new_t, new_t))

    assert cache.get(p) == "version two"


def test_tldr_cache_missing_field_returns_default(tmp_path: Path):
    """无 tldr 字段时返回 '(无 tldr 字段)'。"""
    p = tmp_path / "no_tldr.md"
    p.write_text(
        '---\ntitle: "no_tldr"\nfoo: bar\n---\n\nbody only',
        encoding="utf-8",
    )
    cache = TldrCache.instance()
    assert cache.get(p) == "(无 tldr 字段)"


def test_tldr_cache_file_not_exist(tmp_path: Path):
    """文件不存在不崩溃。"""
    p = tmp_path / "ghost.md"  # 不创建
    cache = TldrCache.instance()
    assert cache.get(p) == "(无 tldr 字段)"


def test_tldr_cache_warm_up_loads_all(tmp_path: Path):
    """warm_up 后所有文章 tldr 已在缓存。"""
    wiki_dir = tmp_path / "wiki"
    articles_dir = wiki_dir / "articles"
    _make_article(articles_dir, "a", "tldr a")
    _make_article(articles_dir, "b", "tldr b")
    _make_article(articles_dir, "c", "tldr c")
    cache = TldrCache.instance()
    n = cache.warm_up(wiki_dir)
    assert n == 3
    # 缓存应已命中所有 3 个文件
    assert len(cache._cache) == 3
    # 抽查一个值
    a_path = articles_dir / "a.md"
    assert cache._cache[str(a_path)][1] == "tldr a"


def test_read_article_tldrs_uses_cache(tmp_path: Path):
    """read_article_tldrs 调用 TldrCache.instance()。"""
    wiki_dir = tmp_path / "wiki"
    articles_dir = wiki_dir / "articles"
    _make_article(articles_dir, "alpha", "alpha summary")

    # 构造图，其中一个节点 source_file 指向该 article
    G = nx.Graph()
    G.add_node(
        "n1",
        label="alpha",
        source_file="articles/alpha.md",
    )
    G.add_node("n2", label="beta", source_file="articles/alpha.md")
    G.add_edge("n1", "n2")

    visited = {"n1", "n2"}

    # mock TldrCache.instance 返回的对象上的 get 方法以确认被调
    with patch.object(TldrCache, "instance", wraps=TldrCache.instance) as spy:
        result = read_article_tldrs(G, visited, wiki_dir, max_tldrs=10)
    assert spy.called
    assert isinstance(result, list)
    assert len(result) >= 1
    # tldr 字段应正确
    assert any(c["tldr"] == "alpha summary" for c in result)


def test_tldr_cache_concurrent_queries_safe(tmp_path: Path):
    """多线程并发读缓存不崩溃（dict 读是 GIL 安全）。"""
    wiki_dir = tmp_path / "wiki"
    articles_dir = wiki_dir / "articles"
    paths = [
        _make_article(articles_dir, f"doc_{i}", f"summary {i}")
        for i in range(10)
    ]
    cache = TldrCache.instance()
    errors = []

    def _worker():
        try:
            for _ in range(50):
                for p in paths:
                    _ = cache.get(p)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发读出错: {errors!r}"
    assert len(cache._cache) == 10


def test_tldr_cache_singleton_reused_across_calls():
    """同进程两次调用 instance() 返回同一对象。"""
    a = TldrCache.instance()
    b = TldrCache.instance()
    assert a is b
