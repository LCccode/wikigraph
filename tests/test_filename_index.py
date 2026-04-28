"""Tests for FIX-A: source_map 反向索引 (filename_index.json)。

Test 名称严格对照架构方案 §2.6 用例清单。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lcwiki.index import (
    load_filename_index,
    save_filename_index,
    rebuild_filename_index,
    filename_index_lookup,
    filename_index_add,
    filename_index_remove,
)


def _make_kb(tmp_path: Path) -> Path:
    """构造最小化的 kb 目录结构。"""
    (tmp_path / "raw" / "inbox").mkdir(parents=True)
    (tmp_path / "raw" / "archive").mkdir(parents=True)
    (tmp_path / "vault" / "meta").mkdir(parents=True)
    (tmp_path / "staging" / "pending").mkdir(parents=True)
    return tmp_path


def _write_inbox_file(kb_root: Path, name: str, content: str) -> Path:
    """在 inbox 写一个文本文件。"""
    p = kb_root / "raw" / "inbox" / name
    p.write_text(content * 20, encoding="utf-8")  # 保证 > 50 字符
    return p


def test_filename_index_cold_start_rebuild(tmp_path: Path):
    """旧 KB 无索引文件，首次 ingest 触发重建。"""
    kb = _make_kb(tmp_path)
    meta = kb / "vault" / "meta"
    # 写一个旧 source_map（模拟老 KB），但不写 filename_index.json
    source_map = {
        "sha_old_001": {
            "original_filename": "doc_old.md",
            "raw_path": "raw/archive/2025-01-01/doc_old",
            "generated_pages": [],
            "uploader": "manual",
        },
        "sha_old_002": {
            "original_filename": "another.md",
            "raw_path": "raw/archive/2025-01-01/another",
            "generated_pages": [],
            "uploader": "manual",
        },
    }
    (meta / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False), encoding="utf-8"
    )
    # 不存在 filename_index.json
    assert not (meta / "filename_index.json").exists()

    # 调 ingest_inbox（inbox 为空，但 ingest_inbox 会在加载完 source_map 后冷启动重建）
    from lcwiki.ingest import ingest_inbox
    ingest_inbox(kb)

    # 验证文件已生成
    assert (meta / "filename_index.json").exists()
    fi = load_filename_index(meta)
    assert "doc_old" in fi
    assert "another" in fi
    assert "sha_old_001" in fi["doc_old"]
    assert "sha_old_002" in fi["another"]


def test_filename_index_new_file_adds_entry(tmp_path: Path):
    """新文件 ingest 后索引包含该 stem。"""
    kb = _make_kb(tmp_path)
    _write_inbox_file(kb, "newdoc.md", "Hello world content for ingest. ")
    from lcwiki.ingest import ingest_inbox
    report = ingest_inbox(kb)
    assert len(report["new"]) == 1
    fi = load_filename_index(kb / "vault" / "meta")
    assert "newdoc" in fi
    assert len(fi["newdoc"]) == 1


def test_filename_index_update_removes_old_sha(tmp_path: Path):
    """同 stem 新文件 ingest，旧 sha 从索引移除。"""
    kb = _make_kb(tmp_path)
    # 第一次 ingest
    _write_inbox_file(kb, "evolving.md", "first content version. ")
    from lcwiki.ingest import ingest_inbox
    ingest_inbox(kb)
    fi_v1 = load_filename_index(kb / "vault" / "meta")
    old_shas_for_stem = list(fi_v1.get("evolving", []))
    assert len(old_shas_for_stem) == 1
    old_sha = old_shas_for_stem[0]

    # 第二次 ingest 同名但内容不同的文件 → update
    _write_inbox_file(kb, "evolving.md", "second different content. ")
    ingest_inbox(kb)

    fi_v2 = load_filename_index(kb / "vault" / "meta")
    # 旧 sha 不应再在 evolving 列表里
    assert old_sha not in fi_v2.get("evolving", [])
    # 应该有新 sha
    assert len(fi_v2["evolving"]) == 1


def test_filename_index_multiple_stems_no_collision(tmp_path: Path):
    """不同 stem 文件不互相影响。"""
    kb = _make_kb(tmp_path)
    _write_inbox_file(kb, "a.md", "content a here. ")
    _write_inbox_file(kb, "b.md", "content b here. ")
    _write_inbox_file(kb, "c.md", "content c here. ")
    from lcwiki.ingest import ingest_inbox
    ingest_inbox(kb)
    fi = load_filename_index(kb / "vault" / "meta")
    assert "a" in fi and "b" in fi and "c" in fi
    assert len(fi["a"]) == 1
    assert len(fi["b"]) == 1
    assert len(fi["c"]) == 1
    # 互不干扰
    assert fi["a"][0] != fi["b"][0] != fi["c"][0]


def test_filename_index_empty_stem_skipped():
    """original_filename 为空/None 不写入索引。"""
    sm = {
        "sha_a": {"original_filename": "", "raw_path": ""},
        "sha_b": {"original_filename": None, "raw_path": ""},
        "sha_c": {"original_filename": "valid.md", "raw_path": ""},
    }
    fi = rebuild_filename_index(sm)
    assert "valid" in fi
    assert "" not in fi
    assert None not in fi
    # 总计只有 valid 一个 stem
    assert len(fi) == 1


def test_filename_index_corrupt_recovery(tmp_path: Path):
    """索引 JSON 损坏时自动重建。"""
    kb = _make_kb(tmp_path)
    meta = kb / "vault" / "meta"
    source_map = {
        "sha_x": {
            "original_filename": "fileX.md",
            "raw_path": "raw/archive/2025-01-01/fileX",
            "generated_pages": [],
            "uploader": "manual",
        }
    }
    (meta / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False), encoding="utf-8"
    )
    # 写一个损坏的 filename_index.json（非合法 JSON）
    (meta / "filename_index.json").write_text("{not valid json", encoding="utf-8")

    # load_filename_index 应返回 {}（_read_json 已处理 JSONDecodeError）
    fi = load_filename_index(meta)
    assert fi == {}

    # ingest_inbox 应触发冷启动重建（fi 为空 + source_map 非空）
    from lcwiki.ingest import ingest_inbox
    ingest_inbox(kb)
    fi2 = load_filename_index(meta)
    assert "fileX" in fi2
    assert "sha_x" in fi2["fileX"]


def test_ingest_conflict_detection_o1(tmp_path: Path):
    """N=2000 source_map 时冲突检测耗时 < 0.1s（性能基准）。"""
    kb = _make_kb(tmp_path)
    meta = kb / "vault" / "meta"
    # 构造 2000 条 source_map
    source_map = {
        f"sha_{i:06d}": {
            "original_filename": f"doc_{i:06d}.md",
            "raw_path": f"raw/archive/2025-01-01/doc_{i:06d}",
            "generated_pages": [],
            "uploader": "manual",
        }
        for i in range(2000)
    }
    (meta / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False), encoding="utf-8"
    )
    # 预先重建索引
    fi = rebuild_filename_index(source_map)
    save_filename_index(fi, meta)

    # 100 次冲突查找耗时（每次都是 O(1) hash 查找）
    start = time.perf_counter()
    for i in range(100):
        _ = filename_index_lookup(f"doc_{i:06d}", fi, exclude_sha="anything")
    elapsed = time.perf_counter() - start
    # 100 次 < 0.1s 即每次 < 1ms（实际应该远小于这个数）
    assert elapsed < 0.1, f"100 lookups took {elapsed:.3f}s, expected <0.1s"
