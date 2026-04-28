"""Tests for FIX-B: concepts_index 增量写 (ConceptsIndexWriter)。

Test 名称严格对照架构方案 §3.7 用例清单。
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from lcwiki.index import ConceptsIndexWriter


def _make_meta(tmp_path: Path) -> Path:
    meta = tmp_path / "vault" / "meta"
    meta.mkdir(parents=True)
    return meta


# 用于多进程测试的顶层函数（必须可 pickle）
def _worker_write_partial(meta_dir_str: str, task_id: str, n_concepts: int) -> None:
    meta_dir = Path(meta_dir_str)
    writer = ConceptsIndexWriter(meta_dir, task_id)
    for i in range(n_concepts):
        cname = f"{task_id}_concept_{i}"
        writer.update(
            cname,
            f"concepts/{cname}.md",
            summary=f"summary for {cname}",
            aliases=[f"{cname}_alias"],
        )
    writer.flush()


def test_writer_flush_creates_partial(tmp_path: Path) -> None:
    """flush 后 partial 文件存在且 JSON 合法"""
    meta = _make_meta(tmp_path)
    writer = ConceptsIndexWriter(meta, "task_001")
    writer.update("ConceptA", "concepts/ConceptA.md", summary="s", aliases=["A1"])
    writer.flush()

    pfile = meta / "concepts_partials" / "task_001.partial.json"
    assert pfile.exists()
    data = json.loads(pfile.read_text(encoding="utf-8"))
    assert "ConceptA" in data
    assert data["ConceptA"]["path"] == "concepts/ConceptA.md"
    assert "A1" in data["ConceptA"]["aliases"]


def test_writer_update_merges_aliases(tmp_path: Path) -> None:
    """同一概念多次 update，aliases 去重合并"""
    meta = _make_meta(tmp_path)
    writer = ConceptsIndexWriter(meta, "task_002")
    writer.update("X", "concepts/X.md", aliases=["a", "b"])
    writer.update("X", "concepts/X.md", aliases=["b", "c"])
    writer.flush()

    pfile = meta / "concepts_partials" / "task_002.partial.json"
    data = json.loads(pfile.read_text(encoding="utf-8"))
    assert sorted(data["X"]["aliases"]) == ["a", "b", "c"]


def test_reduce_merges_all_partials(tmp_path: Path) -> None:
    """3 个 partial 合并后 concepts_index 条目正确"""
    meta = _make_meta(tmp_path)
    for tid in ("t1", "t2", "t3"):
        w = ConceptsIndexWriter(meta, tid)
        w.update(f"C_{tid}", f"concepts/C_{tid}.md", summary=f"s_{tid}")
        w.flush()

    result = ConceptsIndexWriter.reduce(meta)
    assert "C_t1" in result
    assert "C_t2" in result
    assert "C_t3" in result

    # 文件落盘
    idx_file = meta / "concepts_index.json"
    assert idx_file.exists()
    on_disk = json.loads(idx_file.read_text(encoding="utf-8"))
    assert "C_t1" in on_disk and "C_t2" in on_disk and "C_t3" in on_disk


def test_reduce_removes_partial_files(tmp_path: Path) -> None:
    """reduce 后 partial 文件被清除"""
    meta = _make_meta(tmp_path)
    w = ConceptsIndexWriter(meta, "t_clean")
    w.update("Y", "concepts/Y.md")
    w.flush()
    pdir = meta / "concepts_partials"
    assert any(pdir.glob("*.partial.json"))

    ConceptsIndexWriter.reduce(meta)
    assert not any(pdir.glob("*.partial.json"))


def test_reduce_skips_corrupt_partial(tmp_path: Path) -> None:
    """损坏的 partial 文件被跳过，不影响其他"""
    meta = _make_meta(tmp_path)
    w = ConceptsIndexWriter(meta, "t_good")
    w.update("Good", "concepts/Good.md")
    w.flush()

    # 写一个损坏的 partial
    pdir = meta / "concepts_partials"
    bad = pdir / "t_bad.partial.json"
    bad.write_text("{ not valid json", encoding="utf-8")

    result = ConceptsIndexWriter.reduce(meta)
    assert "Good" in result
    # 损坏文件也应被清理（reduce 末尾 unlink 全部）
    assert not bad.exists()


def test_reduce_idempotent(tmp_path: Path) -> None:
    """重复 reduce 结果相同"""
    meta = _make_meta(tmp_path)
    w = ConceptsIndexWriter(meta, "t_idem")
    w.update("Z", "concepts/Z.md", summary="zsum", aliases=["zz"])
    w.flush()

    r1 = ConceptsIndexWriter.reduce(meta)
    r2 = ConceptsIndexWriter.reduce(meta)
    assert r1 == r2
    assert r2["Z"]["path"] == "concepts/Z.md"


def test_concurrent_writes_no_collision(tmp_path: Path) -> None:
    """模拟 5 个进程并发写不同 task_id，reduce 后无丢失"""
    meta = _make_meta(tmp_path)
    procs = []
    for i in range(5):
        p = mp.Process(
            target=_worker_write_partial,
            args=(str(meta), f"proc_{i}", 4),
        )
        procs.append(p)
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    result = ConceptsIndexWriter.reduce(meta)
    # 5 个 proc × 4 concepts = 20 条
    assert len(result) == 20
    for i in range(5):
        for j in range(4):
            assert f"proc_{i}_concept_{j}" in result


def test_crash_recovery_partial_rerun(tmp_path: Path) -> None:
    """compile-write 中途 mock-crash，重跑后 partial 正确

    模拟方式：第一次 update 后不调 flush（崩溃丢内存），
    第二次重新构造 writer，确认能恢复到磁盘已有数据并 flush。
    """
    meta = _make_meta(tmp_path)

    # 第一次：update + flush 一部分（已落盘 partial）
    w1 = ConceptsIndexWriter(meta, "task_crash")
    w1.update("FirstHalf", "concepts/FirstHalf.md", aliases=["fh"])
    w1.flush()  # 模拟第一批落盘

    # 第一次再添加一项但没 flush（模拟崩溃）
    w1.update("LostInCrash", "concepts/LostInCrash.md")
    # 注意：这里故意不 flush

    # 第二次：重新构造 writer（断点续写），应能从 partial 恢复 FirstHalf
    w2 = ConceptsIndexWriter(meta, "task_crash")
    # 验证恢复了第一次 flush 的内容
    assert "FirstHalf" in w2._data
    assert "LostInCrash" not in w2._data  # 这条没 flush 应该没了
    # 重跑该 task：补写 LostInCrash
    w2.update("LostInCrash", "concepts/LostInCrash.md")
    w2.flush()

    result = ConceptsIndexWriter.reduce(meta)
    assert "FirstHalf" in result
    assert "LostInCrash" in result


def test_has_dirty_partials_detection(tmp_path: Path) -> None:
    """flush 后返回 True，reduce 后返回 False"""
    meta = _make_meta(tmp_path)
    assert ConceptsIndexWriter.has_dirty_partials(meta) is False

    w = ConceptsIndexWriter(meta, "t_dirty")
    w.update("D", "concepts/D.md")
    w.flush()
    assert ConceptsIndexWriter.has_dirty_partials(meta) is True

    ConceptsIndexWriter.reduce(meta)
    assert ConceptsIndexWriter.has_dirty_partials(meta) is False


def test_old_kb_no_partial_dir_migrate(tmp_path: Path) -> None:
    """旧 KB 无 partial 目录，reduce 直接返回现有 index"""
    meta = _make_meta(tmp_path)
    # 写一个旧的 concepts_index.json
    existing = {"OldConcept": {
        "path": "concepts/OldConcept.md",
        "aliases": ["oc"],
        "summary": "old summary",
        "article_count": 5,
    }}
    (meta / "concepts_index.json").write_text(
        json.dumps(existing, ensure_ascii=False), encoding="utf-8"
    )

    # partial 目录不存在
    assert not (meta / "concepts_partials").exists()

    result = ConceptsIndexWriter.reduce(meta)
    assert "OldConcept" in result
    assert result["OldConcept"]["article_count"] == 5
