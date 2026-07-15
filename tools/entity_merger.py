#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 实体合并器

锚定: L2_数据模型与核心算法.md §2.9
      L3_接口契约与约束.md §1.3.3

合并去重实体和关系：
- 同 (name, type) 的实体合并为一个（base_info/detail_info/coords/stitch_tags 取并集）
- 关系按 (source_id, target_id, relation_type) 去重（保留最新描述和强度）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Entity, Relation

logger = logging.getLogger(__name__)


def merge(
    entities: "list[Entity]",
    relations: "list[Relation]",
) -> "tuple[list[Entity], list[Relation]]":
    """合并去重实体和关系。

    Args:
        entities: 含 ID 实体列表
        relations: 关系列表

    Returns:
        (合并后实体, 去重后关系)
    """
    merged_entities = _merge_entities(entities)
    merged_relations = _dedupe_relations(relations)
    logger.info(f"实体合并: {len(entities)} → {len(merged_entities)}; "
                f"关系去重: {len(relations)} → {len(merged_relations)}")
    return merged_entities, merged_relations


def _extract_t_main_volume(entity_id: str) -> str | None:
    """从实体 id 中提取 T_main 卷索引（v0.5.0 A3）。

    角色 id 格式: "C_{name}__T_main_vol_{idx}" → 提取 "idx"
    非角色 id 或无卷索引 → 返回 None
    """
    import re
    m = re.match(r"^[A-Z]_.+?__T_main_vol_(\d+)$", entity_id)
    if m:
        return m.group(1)
    return None


def _merge_entities(entities: "list[Entity]") -> "list[Entity]":
    """合并同名同类型的实体（v0.5.0 A3: 角色类型按多档案合并）。

    合并规则：
    - 角色类型: 合并键 (name, type, t_main_volume) — 不同卷不合并
    - 非角色类型: 合并键 (name, type) — 行为不变
    - base_info: 取并集（aliases 合并去重）
    - detail_info: 取并集
    - coords: 各维度取并集（T/L/C/E/K 列表合并去重，R 字典合并）
    - stitch_tags: 取并集
    - source_chapter: 取最早出现的章节
    - char_offset: 取最小的
    """
    from .models import MULTI_PROFILE_TYPES

    groups: dict[tuple, "Entity"] = {}
    order: list[tuple] = []

    for entity in entities:
        # v0.5.0 A3: 角色类型按 (name, type, t_main_volume) 合并
        if entity.type in MULTI_PROFILE_TYPES:
            vol = _extract_t_main_volume(entity.id)
            key = (entity.name, entity.type, vol)
        else:
            key = (entity.name, entity.type)

        if key not in groups:
            groups[key] = entity
            order.append(key)
        else:
            # 合并到已有实体
            existing = groups[key]
            existing.base_info = _merge_dict_union(existing.base_info, entity.base_info)
            existing.detail_info = _merge_dict_union(existing.detail_info, entity.detail_info)
            existing.stitch_tags = _merge_dict_union(existing.stitch_tags, entity.stitch_tags)
            existing.coords = _merge_coords(existing.coords, entity.coords)
            # 取最早出现的章节
            if entity.char_offset < existing.char_offset:
                existing.char_offset = entity.char_offset
                existing.source_chapter = entity.source_chapter
            elif entity.source_chapter and not existing.source_chapter:
                existing.source_chapter = entity.source_chapter

    return [groups[key] for key in order]


def _merge_dict_union(a: dict, b: dict) -> dict:
    """合并两个字典，对列表值取并集去重，对其他值取非空覆盖。"""
    result = dict(a)
    for k, v in b.items():
        if k not in result:
            result[k] = v
        else:
            existing = result[k]
            if isinstance(existing, list) and isinstance(v, list):
                # 列表合并去重
                merged = list(existing)
                for item in v:
                    if item not in merged:
                        merged.append(item)
                result[k] = merged
            elif isinstance(existing, dict) and isinstance(v, dict):
                result[k] = _merge_dict_union(existing, v)
            elif not existing and v:
                # 非空覆盖空
                result[k] = v
            # else: 保留原值
    return result


def _merge_coords(a: dict, b: dict) -> dict:
    """合并六维坐标。

    T/L/C/E/K: 列表合并去重
    R: 字典合并
    """
    result: dict = {}
    list_keys = ("T", "L", "C", "E", "K")
    for k in list_keys:
        va = a.get(k, [])
        vb = b.get(k, [])
        # 统一为列表
        if isinstance(va, str):
            va = [va] if va else []
        if isinstance(vb, str):
            vb = [vb] if vb else []
        merged = list(va)
        for item in vb:
            if item not in merged:
                merged.append(item)
        result[k] = merged
    # R 字典合并
    ra = a.get("R", {})
    rb = b.get("R", {})
    result["R"] = _merge_dict_union(ra, rb)
    return result


def _dedupe_relations(relations: "list[Relation]") -> "list[Relation]":
    """关系去重。

    按 (source_id, target_id, relation_type) 去重：
    - 后出现的覆盖前面的 description 和 strength
    - source_chapter 取最早的
    """
    seen: dict[tuple[str, str, str], "Relation"] = {}
    order: list[tuple[str, str, str]] = []

    for rel in relations:
        key = (rel.source_id, rel.target_id, rel.relation_type)
        if key not in seen:
            seen[key] = rel
            order.append(key)
        else:
            existing = seen[key]
            # 保留最新描述
            if rel.description:
                existing.description = rel.description
            # 保留更强强度（strong > weak）
            if rel.strength == "strong" and existing.strength == "weak":
                existing.strength = "strong"
            # source_chapter 取最早的
            if rel.source_chapter and not existing.source_chapter:
                existing.source_chapter = rel.source_chapter

    return [seen[key] for key in order]
