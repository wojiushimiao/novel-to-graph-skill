#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 章节标题抽样工具

锚定: L3_接口契约与约束.md §1.1.1

从 chunks 中抽样章节标题，供智能体传给 LLM 做全局结构概览。
当章节数超过上限时等间距抽样，保留首尾章节以保证覆盖范围。
"""

from __future__ import annotations

import structlog

try:
    from .models import Chunk
except ImportError:
    from models import Chunk

logger = structlog.get_logger(__name__)

# first_100_chars 截断长度
_FIRST_N_CHARS = 100


def sample_chapter_titles(
    chunks: list[Chunk], max_samples: int = 200
) -> list[dict]:
    """从 chunks 中抽样章节标题。

    按 chapter 字段去重（按首次出现顺序），每个唯一章节生成一条记录。
    章节数不超过 max_samples 时全量保留；超过时等间距抽样，保留首尾。

    Args:
        chunks: 文本块列表（Chunk dataclass 实例）
        max_samples: 最大抽样数，默认 200

    Returns:
        章节标题记录列表，每条形如::

            {"chapter_idx": int, "title": str, "first_100_chars": str}

        - chapter_idx: 章节在去重序列中的序号（0-based）
        - title: 章节标题；为空时用 first_100_chars 填充
        - first_100_chars: 该章节首个 chunk 内容的前 100 字符

    Raises:
        ValueError: chunks 为空时抛出
    """
    if not chunks:
        raise ValueError("chunks 不能为空")

    # 按首次出现顺序去重，提取唯一章节
    seen: set[str] = set()
    chapters: list[dict] = []
    for chunk in chunks:
        if chunk.chapter in seen:
            continue
        seen.add(chunk.chapter)
        first_100 = chunk.content[:_FIRST_N_CHARS]
        title = chunk.chapter if chunk.chapter else first_100
        chapters.append({"title": title, "first_100_chars": first_100})

    total = len(chapters)
    indices = (
        list(range(total)) if total <= max_samples else _even_indices(total, max_samples)
    )

    result = [
        {
            "chapter_idx": idx,
            "title": chapters[idx]["title"],
            "first_100_chars": chapters[idx]["first_100_chars"],
        }
        for idx in indices
    ]

    logger.info(
        "章节标题抽样完成",
        total_chapters=total,
        sampled=len(result),
        max_samples=max_samples,
    )
    return result


def _even_indices(n: int, k: int) -> list[int]:
    """从 [0, n) 中等间距抽取 k 个索引，保留首尾。

    Args:
        n: 元素总数（n > 0）
        k: 抽样数（k < n）

    Returns:
        升序索引列表，首元素为 0，末元素为 n-1
    """
    if k >= n:
        return list(range(n))
    if k <= 0:
        return []
    if k == 1:
        return [0]
    # 等间距：步长 (n-1)/(k-1)，含 0 与 n-1
    raw = [round(i * (n - 1) / (k - 1)) for i in range(k)]
    # 去重保序（极端 n/k 比例下 round 可能产生重复索引）
    seen: set[int] = set()
    result: list[int] = []
    for idx in raw:
        if idx not in seen:
            seen.add(idx)
            result.append(idx)
    return result
