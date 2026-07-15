#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 重要度量化器

锚定: L2_数据模型与核心算法.md §2.7
      L3_接口契约与约束.md §1.3.1

将定性 importance (high/medium/low) 映射为数值 importance_score。
"""

from __future__ import annotations

import logging

from .models import IMPORTANCE_SCORE_MAP

logger = logging.getLogger(__name__)


def map_importance(items: list[dict]) -> list[dict]:
    """定性→定量映射。

    为每个 item 添加 importance_score 字段：
    - high → 0.85
    - medium → 0.50
    - low → 0.15

    Args:
        items: 清洗后的字典列表（已通过 Schema 校验）

    Returns:
        含 importance_score 字段的字典列表（不修改原字典）
    """
    result: list[dict] = []
    for item in items:
        new_item = dict(item)
        importance = new_item.get("importance", "low")
        new_item["importance_score"] = IMPORTANCE_SCORE_MAP.get(importance, 0.15)
        result.append(new_item)
    logger.info(f"重要度量化完成: {len(result)} 条")
    return result


def get_score(importance: str) -> float:
    """获取单个 importance 的数值映射。

    Args:
        importance: high/medium/low

    Returns:
        0.85 / 0.50 / 0.15
    """
    return IMPORTANCE_SCORE_MAP.get(importance, 0.15)
