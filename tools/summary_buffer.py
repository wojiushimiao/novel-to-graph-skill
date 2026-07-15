#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 短期记忆滑动窗口（SummaryBuffer）

锚定: v0.4.1_plan_final.md §T-C1
功能: 为 T_main 增量压缩提供缓冲机制，按 chunk 顺序累积短期摘要。

核心逻辑:
1. 滑动窗口大小：默认 50 个 chunk 摘要
2. 每个 chunk 摘要格式：100-300 字，含发生事件/涉及角色/地点/规则变动
3. 每 flush_interval 个 chunk 触发一次缓冲刷新（flush）
4. flush 时输出当前窗口内的所有摘要 + 窗口元数据
5. 窗口溢出时自动丢弃最旧条目（FIFO）
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    """内部条目：chunk 索引 + 摘要文本 + 时间戳。"""
    chunk_index: int
    summary: str
    timestamp: float = field(default_factory=time.time)


class SummaryBuffer:
    """短期记忆滑动窗口。

    Args:
        window_size: 窗口大小（最大条目数），默认 50
        flush_interval: flush 触发间隔（每 N 条触发一次），默认 10
    """

    def __init__(self, window_size: int = 50, flush_interval: int = 10) -> None:
        if window_size <= 0:
            raise ValueError(f"window_size 必须为正数，收到 {window_size}")
        if flush_interval <= 0:
            raise ValueError(f"flush_interval 必须为正数，收到 {flush_interval}")

        self._window_size = window_size
        self._flush_interval = flush_interval
        self._buffer: deque[_Entry] = deque(maxlen=window_size)
        self._since_last_flush = 0

    def add(self, chunk_index: int, summary: str) -> bool:
        """添加一个 chunk 摘要到缓冲区。

        Args:
            chunk_index: chunk 索引（0-based 递增）
            summary: 摘要文本（100-300 字）

        Returns:
            True = 触发 flush 信号（达到 flush_interval）
            False = 未触发 flush
        """
        if not isinstance(summary, str):
            raise TypeError(f"summary 必须为 str，收到 {type(summary).__name__}")

        entry = _Entry(chunk_index=chunk_index, summary=summary)
        self._buffer.append(entry)
        self._since_last_flush += 1

        if self._since_last_flush >= self._flush_interval:
            return True
        return False

    def flush(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """刷新缓冲区，返回当前窗口内所有摘要。

        Returns:
            (summaries, meta)
            summaries: 按 chunk_index 升序排列的摘要列表，每个元素含:
                - chunk_index: int
                - summary: str
                - timestamp: float
            meta: 窗口元数据，含:
                - count: int - 摘要数量
                - start_chunk: int - 最旧 chunk 索引（-1 表示空）
                - end_chunk: int - 最新 chunk 索引（-1 表示空）
        """
        if not self._buffer:
            return [], {"count": 0, "start_chunk": -1, "end_chunk": -1}

        # 按 chunk_index 升序排列
        sorted_entries = sorted(self._buffer, key=lambda e: e.chunk_index)
        summaries = [
            {
                "chunk_index": e.chunk_index,
                "summary": e.summary,
                "timestamp": e.timestamp,
            }
            for e in sorted_entries
        ]

        meta = {
            "count": len(summaries),
            "start_chunk": sorted_entries[0].chunk_index,
            "end_chunk": sorted_entries[-1].chunk_index,
        }

        # 仅重置计数器，保留缓冲区内容（滑动窗口语义）
        # dequeue(maxlen=window_size) 自动处理 FIFO 溢出
        self._since_last_flush = 0

        return summaries, meta

    def clear(self) -> None:
        """清空缓冲区。"""
        self._buffer.clear()
        self._since_last_flush = 0

    def window_range(self) -> tuple[int, int]:
        """返回当前窗口的 (start_chunk, end_chunk)。

        Returns:
            (start, end): 窗口内最旧和最新的 chunk 索引
            空窗口返回 (-1, -1)
        """
        if not self._buffer:
            return -1, -1

        entries = list(self._buffer)
        start = min(e.chunk_index for e in entries)
        end = max(e.chunk_index for e in entries)
        return start, end

    @property
    def window_size(self) -> int:
        """窗口大小。"""
        return self._window_size

    @property
    def flush_interval(self) -> int:
        """flush 间隔。"""
        return self._flush_interval

    @property
    def size(self) -> int:
        """当前缓冲区条目数。"""
        return len(self._buffer)
