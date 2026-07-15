#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人物小传工具（v0.5.1 B2）。

锚定: v0.5.1_升级/00_技术锚定/L1_模块边界与需求索引.md §FR-04
"""

from __future__ import annotations

import logging
import re
from typing import Any

try:
    from .models import Entity, Relation
except ImportError:
    from models import Entity, Relation

logger = logging.getLogger(__name__)

# 角色多档案 id 格式: C_{name}__T_main_vol_{idx}
_ID_PATTERN = re.compile(r"^[A-Z]_(.+?)__T_main_vol_(\d+)$")


def prepare_character_synthesis(
    entities: list[Entity],
    evolves_to_relations: list[Relation],
) -> list[dict[str, Any]]:
    """准备人物小传数据（v0.5.1 B2）。

    按角色名分组，沿 evolves_to 链按卷索引排序，
    过滤掉仅出现在 1 卷中的角色。

    Args:
        entities: 所有实体列表
        evolves_to_relations: evolves_to 关系列表

    Returns:
        [{"name": str, "volumes": [{"vol_idx": int, "entity_id": str, "info": str}]}]
        仅包含出现在 ≥2 卷的角色，按角色名排序

    Note:
        卷链由实体 id 解析得出（与 graph_builder.build_evolves_to_relations
        一致），evolves_to_relations 为契约预留参数。
    """
    # 按角色名分组: {name: [(vol_idx, entity), ...]}
    groups: dict[str, list[tuple[int, Entity]]] = {}
    for ent in entities:
        if ent.type != "character":
            continue
        m = _ID_PATTERN.match(ent.id)
        if not m:
            # 旧格式 id（C_{name}，无卷后缀）或畸形 id，跳过
            continue
        name = m.group(1)
        vol_idx = int(m.group(2))
        groups.setdefault(name, []).append((vol_idx, ent))

    # 每组按卷索引升序排序，过滤仅 1 卷的角色，构建输出
    result: list[dict[str, Any]] = []
    for name, entries in groups.items():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda x: x[0])
        result.append({
            "name": name,
            "volumes": [
                {
                    "vol_idx": vol_idx,
                    "entity_id": ent.id,
                    "info": ent.info,
                }
                for vol_idx, ent in entries
            ],
        })

    # 按角色名排序，保证输出确定性
    result.sort(key=lambda item: item["name"])

    logger.info(
        f"人物小传数据准备完成: {len(result)} 个多卷角色 "
        f"(输入 {len(entities)} 实体)"
    )
    return result


def create_synthesis_entity(
    name: str,
    info: str,
    volumes_covered: list[int],
    source_profiles: list[str],
) -> Entity:
    """创建人物小传 synthesis 实体（v0.5.1 B2）。

    Args:
        name: 角色名（如 "莫凡"）
        info: LLM 生成的人物小传（5 段结构）
        volumes_covered: 覆盖的卷索引列表（如 [0, 1, 2]）
        source_profiles: 源档案 id 列表（如 ["C_莫凡__T_main_vol_0", ...]）

    Returns:
        Entity 对象，id 格式为 C_{name}__synthesis

    Note:
        Entity 数据类无 importance 字段，故将 importance="high"
        置于 base_info 中（与 schema_specification.md §4.8 契约一致）。
    """
    return Entity(
        id=f"C_{name}__synthesis",
        name=name,
        type="character",
        coords={"T": "synthesis", "C": name},
        base_info={
            "category": "synthesis",
            "volumes_count": len(volumes_covered),
            "importance": "high",
        },
        detail_info={
            "volumes_covered": volumes_covered,
            "source_profiles": source_profiles,
        },
        info=info,
    )
