#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · ID 路由器

锚定: L2_数据模型与核心算法.md §2.8
      L3_接口契约与约束.md §1.3.2

为实体路由 ID：
- 已有 DB 中存在同 (name, type) → 复用已有 ID（Upsert 增量更新）
- 不存在 → 生成新 ID: "{type[0].upper()}_{name}"
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Entity

logger = logging.getLogger(__name__)


def route(
    entities: "list[Entity]",
    conn: sqlite3.Connection | None = None,
) -> "list[Entity]":
    """为实体路由 ID（Upsert 查找已有 / 生成新 ID）。

    Args:
        entities: 待路由实体列表
        conn: 已有 DB 连接（用于查找已有实体），None 时全部生成新 ID

    Returns:
        含合法 ID 的实体列表（原列表就地修改后返回）
    """
    # 若有 DB 连接，预加载已有实体索引 {(name, type): id}
    existing_index: dict[tuple[str, str], str] = {}
    if conn is not None:
        try:
            for row in conn.execute("SELECT id, name, type FROM entities"):
                existing_index[(row[1], row[2])] = row[0]
            logger.info(f"加载已有实体索引: {len(existing_index)} 条")
        except sqlite3.Error as exc:
            logger.warning(f"加载已有实体索引失败: {exc}; 将全部生成新 ID")

    new_count = 0
    reuse_count = 0

    for entity in entities:
        key = (entity.name, entity.type)
        if key in existing_index:
            entity.id = existing_index[key]
            reuse_count += 1
        else:
            entity.id = generate_id(entity.type, entity.name)
            existing_index[key] = entity.id
            new_count += 1

    logger.info(f"ID 路由完成: 新建 {new_count}, 复用 {reuse_count}")
    return entities


def generate_id(entity_type: str, name: str) -> str:
    """生成实体 ID。

    Args:
        entity_type: 实体类型 (character/location/event/item/rule/system)
        name: 实体名称

    Returns:
        "{type[0].upper()}_{name}"，如 "C_莫凡"
    """
    if not entity_type:
        prefix = "X"
    else:
        prefix = entity_type[0].upper()
    # 名称中不能包含特殊分隔符
    safe_name = name.replace("\n", " ").strip()[:50]
    return f"{prefix}_{safe_name}"
