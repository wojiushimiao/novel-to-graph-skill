#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B1 chapter_title_sampler.py 测试

锚定: track_B_plan.md §T-B1
检查点: CP-B1.1 (章节标题抽样 ≤200 上限) + CP-B1.2 (等间距抽样保留首尾)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 tools 目录加入路径（novel-to-graph-skill 目录名含连字符，无法作为 Python 包；
# 同时避免与 06_核心代码/tools 包名冲突）
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from chapter_title_sampler import sample_chapter_titles  # noqa: E402
from models import Chunk  # noqa: E402


# ─── 辅助函数 ────────────────────────────────────────────────

def _make_chunk(index: int, chapter: str, content: str = "默认内容") -> Chunk:
    """构造测试用 Chunk 实例。"""
    return Chunk(
        index=index,
        content=content,
        chapter=chapter,
        char_offset=0,
        char_count=len(content),
        chunk_id=f"id_{index}",
    )


def _make_chunks(n: int, content_prefix: str = "章节内容") -> list[Chunk]:
    """构造 n 个不同章节的 Chunk 列表。"""
    return [
        _make_chunk(i, f"第{i + 1}章", content=f"{content_prefix}_{i + 1}")
        for i in range(n)
    ]


# ─── CP-B1.1: 章节数 ≤ max_samples 时全量保留 ────────────────

class TestFullRetention:
    """验证章节数不超过上限时全量保留。"""

    def test_few_chapters_all_preserved(self):
        """章节数远小于 200 时全部保留。"""
        chunks = _make_chunks(5)
        result = sample_chapter_titles(chunks)
        assert len(result) == 5

    def test_exactly_max_samples(self):
        """章节数恰好等于 max_samples 时全量保留。"""
        chunks = _make_chunks(200)
        result = sample_chapter_titles(chunks, max_samples=200)
        assert len(result) == 200

    def test_chapter_idx_sequential(self):
        """全量保留时 chapter_idx 从 0 连续递增。"""
        chunks = _make_chunks(5)
        result = sample_chapter_titles(chunks)
        assert [r["chapter_idx"] for r in result] == [0, 1, 2, 3, 4]

    def test_title_correct(self):
        """全量保留时 title 与 chunk.chapter 一致。"""
        chunks = _make_chunks(3)
        result = sample_chapter_titles(chunks)
        assert result[0]["title"] == "第1章"
        assert result[2]["title"] == "第3章"


# ─── CP-B1.2: 章节数 > max_samples 时等间距抽样保留首尾 ──────

class TestEvenSampling:
    """验证章节数超过上限时等间距抽样，保留首尾。"""

    def test_sample_count_within_limit(self):
        """抽样后数量不超过 max_samples。"""
        chunks = _make_chunks(300)
        result = sample_chapter_titles(chunks, max_samples=10)
        assert len(result) <= 10

    def test_first_chapter_preserved(self):
        """首章节必须保留。"""
        chunks = _make_chunks(300)
        result = sample_chapter_titles(chunks, max_samples=10)
        assert result[0]["title"] == "第1章"
        assert result[0]["chapter_idx"] == 0

    def test_last_chapter_preserved(self):
        """末章节必须保留。"""
        chunks = _make_chunks(300)
        result = sample_chapter_titles(chunks, max_samples=10)
        assert result[-1]["title"] == "第300章"
        assert result[-1]["chapter_idx"] == 299

    def test_indices_ascending(self):
        """抽样后 chapter_idx 严格递增。"""
        chunks = _make_chunks(300)
        result = sample_chapter_titles(chunks, max_samples=10)
        idxs = [r["chapter_idx"] for r in result]
        assert idxs == sorted(idxs), "chapter_idx 必须递增"
        assert len(set(idxs)) == len(idxs), "chapter_idx 不得重复"

    def test_default_max_samples_200(self):
        """默认 max_samples=200，300 章抽样后 ≤200。"""
        chunks = _make_chunks(300)
        result = sample_chapter_titles(chunks)
        assert len(result) <= 200
        assert result[0]["chapter_idx"] == 0
        assert result[-1]["chapter_idx"] == 299


# ─── 空标题填充 first_100_chars ───────────────────────────────

class TestEmptyTitleFill:
    """验证 title 为空时用 first_100_chars 填充。"""

    def test_empty_title_filled(self):
        """chapter 为空字符串时 title 等于 first_100_chars。"""
        chunk = _make_chunk(0, "", content="这是一段开头内容用于填充标题")
        result = sample_chapter_titles([chunk])
        assert result[0]["title"] == result[0]["first_100_chars"]
        assert result[0]["title"] == "这是一段开头内容用于填充标题"

    def test_first_100_chars_truncated(self):
        """content 超过 100 字符时 first_100_chars 截断为前 100 字符。"""
        long_content = "A" * 150
        chunk = _make_chunk(0, "第1章", content=long_content)
        result = sample_chapter_titles([chunk])
        assert len(result[0]["first_100_chars"]) == 100
        assert result[0]["first_100_chars"] == "A" * 100

    def test_first_100_chars_short_content(self):
        """content 不足 100 字符时 first_100_chars 为全部 content。"""
        short_content = "短内容"
        chunk = _make_chunk(0, "第1章", content=short_content)
        result = sample_chapter_titles([chunk])
        assert result[0]["first_100_chars"] == "短内容"

    def test_first_100_chars_always_present(self):
        """有标题时 first_100_chars 也必须提供（补充语义）。"""
        chunk = _make_chunk(0, "第1章", content="补充内容")
        result = sample_chapter_titles([chunk])
        assert "first_100_chars" in result[0]
        assert result[0]["first_100_chars"] == "补充内容"


# ─── chunks 为空时抛 ValueError ──────────────────────────────

class TestEmptyChunks:
    """验证 chunks 为空时抛出 ValueError。"""

    def test_empty_list_raises(self):
        """空列表必须抛 ValueError。"""
        with pytest.raises(ValueError):
            sample_chapter_titles([])


# ─── 多 chunk 同章节去重 ─────────────────────────────────────

class TestDeduplication:
    """验证同一章节的多个 chunk 去重为一个条目。"""

    def test_same_chapter_deduplicated(self):
        """同一 chapter 的多个 chunk 只保留一个条目。"""
        chunks = [
            _make_chunk(0, "第1章", content="内容1"),
            _make_chunk(1, "第1章", content="内容2"),
            _make_chunk(2, "第2章", content="内容3"),
        ]
        result = sample_chapter_titles(chunks)
        assert len(result) == 2
        assert result[0]["title"] == "第1章"
        assert result[1]["title"] == "第2章"

    def test_first_chunk_content_used(self):
        """去重后 first_100_chars 取自该章节首个 chunk。"""
        chunks = [
            _make_chunk(0, "第1章", content="首段内容"),
            _make_chunk(1, "第1章", content="后续内容"),
        ]
        result = sample_chapter_titles(chunks)
        assert result[0]["first_100_chars"] == "首段内容"

    def test_dedup_preserves_order(self):
        """去重后章节顺序按首次出现顺序。"""
        chunks = [
            _make_chunk(0, "第三章", content="c3"),
            _make_chunk(1, "第一章", content="c1"),
            _make_chunk(2, "第三章", content="c3b"),
        ]
        result = sample_chapter_titles(chunks)
        assert len(result) == 2
        assert result[0]["title"] == "第三章"
        assert result[1]["title"] == "第一章"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
