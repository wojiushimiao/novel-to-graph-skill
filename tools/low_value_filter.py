#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 低价值过滤器

锚定: L2_数据模型与核心算法.md §2.6
      L3_接口契约与约束.md §1.2.3

丢弃低价值记录：importance == "low" 且 coords.R 为空 → 丢弃。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def filter(items: list[dict]) -> list[dict]:
    """丢弃低价值记录。

    规则：
    - importance == "low" 且 coords.R 为空（无规则变动）→ 丢弃
    - 其他情况 → 保留

    Args:
        items: 通过 Schema 校验的字典列表

    Returns:
        高价值记录列表
    """
    result: list[dict] = []
    dropped = 0
    for item in items:
        if _is_low_value(item):
            dropped += 1
            continue
        result.append(item)

    logger.info(f"低价值过滤完成: 丢弃 {dropped}, 保留 {len(result)}")
    return result


def _is_low_value(item: dict) -> bool:
    """判定是否为低价值记录。"""
    importance = item.get("importance")
    if importance != "low":
        return False

    coords = item.get("coords", {})
    r = coords.get("R")
    # v0.4.0: R 为字符串（如 "R_power"）→ 有规则，非低价值
    if isinstance(r, str):
        return not bool(r.strip())
    # v0.3.0 遗留: R 为 dict（{subtype, rule_name}）
    if not r:
        return True
    if not r.get("subtype"):
        return True
    if not r.get("rule_name"):
        return True
    return False
