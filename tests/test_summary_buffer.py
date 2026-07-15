#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-C1 summary_buffer.py 测试

锚定: v0.4.1_plan_final.md §T-C1
检查点: CP-C1.1 (窗口溢出自动丢弃) / CP-C1.2 (flush 按 chunk_index 有序) / CP-C1.3 (空窗口 flush 不报错)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from summary_buffer import SummaryBuffer  # noqa: E402


# ─── CP-C1.1: 窗口溢出自动丢弃 ──────────────────────────

class TestWindowOverflow:
    """验证窗口溢出时自动丢弃最旧条目。"""

    def test_overflow_drops_oldest(self):
        """窗口大小 50，添加 55 条后，最旧的 5 条被丢弃。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        for i in range(55):
            buf.add(i, f"摘要_{i}")

        # 窗口内应只有 50 条
        summaries, meta = buf.flush()
        assert len(summaries) == 50
        # 最旧的 5 条（0-4）被丢弃，最旧应为 5
        assert summaries[0]["chunk_index"] == 5
        # 最新应为 54
        assert summaries[-1]["chunk_index"] == 54

    def test_add_returns_flush_signal(self):
        """每 flush_interval 条触发一次 flush 信号。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        for i in range(9):
            assert buf.add(i, f"摘要_{i}") is False
        # 第 10 条触发 flush 信号
        assert buf.add(9, "摘要_9") is True


# ─── CP-C1.2: flush 按 chunk_index 有序 ──────────────────

class TestFlushOrdered:
    """验证 flush 返回的摘要列表按 chunk_index 有序。"""

    def test_flush_returns_ordered_summaries(self):
        """flush 后返回的摘要按 chunk_index 升序排列。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        # 乱序添加（但 chunk_index 递增）
        for i in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
            buf.add(i, f"摘要_{i}")

        summaries, meta = buf.flush()
        assert len(summaries) == 10
        for i in range(10):
            assert summaries[i]["chunk_index"] == i

    def test_flush_does_not_clear_buffer(self):
        """flush 后缓冲区不清空，保留滑动窗口内容。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        for i in range(10):
            buf.add(i, f"摘要_{i}")

        summaries1, _ = buf.flush()
        assert len(summaries1) == 10
        assert buf.size == 10

        # 再次 flush 仍返回相同内容（未添加新条目）
        summaries2, _ = buf.flush()
        assert len(summaries2) == 10

    def test_flush_preserves_window(self):
        """flush 保留窗口，window_range() 仍返回正确范围。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        for i in range(10):
            buf.add(i, f"摘要_{i}")

        buf.flush()
        assert buf.size == 10
        start, end = buf.window_range()
        assert start == 0
        assert end == 9

    def test_clear_empties_buffer(self):
        """clear() 清空缓冲区，size 归零，window_range() 返回 (-1, -1)。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        for i in range(10):
            buf.add(i, f"摘要_{i}")

        buf.clear()
        assert buf.size == 0
        start, end = buf.window_range()
        assert start == -1
        assert end == -1


# ─── CP-C1.3: 空窗口 flush 不报错 ───────────────────────

class TestEmptyFlush:
    """验证空窗口 flush 返回空列表不报错。"""

    def test_empty_flush_returns_empty_list(self):
        """从未添加任何条目，flush 返回空列表。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        summaries, meta = buf.flush()
        assert summaries == []
        assert isinstance(summaries, list)

    def test_window_range_empty(self):
        """空窗口的 window_range 返回 (-1, -1)。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        start, end = buf.window_range()
        assert start == -1
        assert end == -1

    def test_window_range_after_add(self):
        """添加条目后 window_range 返回正确的 (start, end)。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        for i in range(5, 10):
            buf.add(i, f"摘要_{i}")
        start, end = buf.window_range()
        assert start == 5
        assert end == 9


# ─── 摘要格式验证 ──────────────────────────────────────

class TestSummaryFormat:
    """验证摘要数据结构格式。"""

    def test_summary_contains_required_fields(self):
        """每个摘要含 chunk_index + summary + timestamp。"""
        buf = SummaryBuffer(window_size=50, flush_interval=10)
        buf.add(42, "莫凡觉醒雷系和光系")

        summaries, _ = buf.flush()
        assert len(summaries) == 1
        s = summaries[0]
        assert s["chunk_index"] == 42
        assert s["summary"] == "莫凡觉醒雷系和光系"
        assert "timestamp" in s
