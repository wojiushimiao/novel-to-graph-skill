#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 时序骨架构建工具

锚定: L3_接口契约与约束.md §1.1.2
      L2_数据模型与核心算法.md §2.6 (时序骨架构建)
      v0.4.1_plan_final.md §T-C3 (增量模式 + 动态调整)

将剧情模块列表转换为 E_module 实体 + T_main 关系的时序骨架。
工具函数无状态，不调用 LLM，所有状态由智能体传递。

v0.4.1 升级:
- 保留原 build_skeleton（一次性模式，向后兼容）
- 新增 Skeleton dataclass（三层实体结构）
- 新增 build_skeleton_incremental（增量模式，输入 cluster_results）
- 新增 adjust_skeleton（动态调整：合并/分裂/重链接）
- 新增 finalize_skeleton（全书完成后稳定化）

三层实体结构（v0.4.1）:
    T_main 实体（剧情卷，5-20个）
      ↓ HAS_MODULE 关系
    E_module 实体（每卷 ≤8 个）
      ↓ T_main 关系（模块间时序）
    E_module → E_module
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

try:
    from .models import Entity, Relation
except ImportError:
    from models import Entity, Relation

logger = logging.getLogger(__name__)


# ─── v0.4.1 常量 ──────────────────────────────────────────

MIN_T_MAIN_VOLUMES = 5
MAX_T_MAIN_VOLUMES = 20
MAX_E_MODULES_PER_VOLUME = 8


# ============================================================
# v0.4.0 一次性模式（向后兼容，保留原接口）
# ============================================================

def build_skeleton(
    plot_modules: list[dict],
) -> tuple[list[Entity], list[Relation]]:
    """构建时序骨架（一次性模式）。

    将剧情模块列表转换为 E_module 实体列表和 T_main 关系列表。
    每个模块转为一个 E_module 实体，相邻模块间建立 T_main 关系，
    形成线性时序主轴。

    Args:
        plot_modules: 剧情模块列表，每项格式::

            {
                "name": str,                  # 模块名称
                "chapter_range": [start, end], # 章节范围
                "theme": str,                  # 主题
                "stage_position": str,         # 阶段位置（开局/发展/高潮等）
            }

    Returns:
        (E_module 实体列表, T_main 关系列表) 的二元组。
        - 实体数量 = len(plot_modules)
        - 关系数量 = len(plot_modules) - 1（相邻模块间）
        - 每个实体 type 为 ``"E_module"``，ID 格式 ``"E_module_{name}"``
        - 每个实体 coords.T 为自身 ID
        - 第一个模块无入边，最后一个模块无出边

    Raises:
        ValueError: plot_modules 为空或仅含 1 个模块时抛出

    Example:
        >>> modules = [
        ...     {"name": "开局", "chapter_range": [1, 10], "theme": "t1", "stage_position": "开局"},
        ...     {"name": "发展", "chapter_range": [11, 20], "theme": "t2", "stage_position": "发展"},
        ... ]
        >>> entities, relations = build_skeleton(modules)
        >>> len(entities), len(relations)
        (2, 1)
        >>> relations[0].relation_type
        'T_main'
    """
    if not plot_modules or len(plot_modules) < 2:
        raise ValueError(
            f"plot_modules 至少需要 2 个模块才能构建时序骨架，"
            f"实际提供 {len(plot_modules) if plot_modules else 0} 个"
        )

    # ─── 构建 E_module 实体 ──────────────────────────────────
    entities: list[Entity] = []
    for mod in plot_modules:
        name = mod["name"]
        entity_id = f"E_module_{name}"
        entity = Entity(
            id=entity_id,
            name=name,
            type="E_module",
            coords={"T": entity_id},
            base_info={
                "chapter_range": mod.get("chapter_range", []),
                "theme": mod.get("theme", ""),
                "stage_position": mod.get("stage_position", ""),
            },
        )
        entities.append(entity)

    # ─── 构建 T_main 关系（仅相邻模块）────────────────────────
    relations: list[Relation] = []
    for i in range(len(entities) - 1):
        rel = Relation(
            source_id=entities[i].id,
            target_id=entities[i + 1].id,
            relation_type="T_main",
            strength="strong",
        )
        relations.append(rel)

    logger.info(
        f"时序骨架构建完成(一次性模式): {len(entities)} 个 E_module 实体, "
        f"{len(relations)} 条 T_main 关系"
    )
    return entities, relations


# ============================================================
# v0.4.1 增量模式 + 动态调整
# ============================================================

@dataclass
class Skeleton:
    """时序骨架（v0.4.1 三层实体结构）。

    锚定: v0.4.1_plan_final.md §T-C3 Skeleton 数据结构

    三层结构:
        T_main 实体（剧情卷，5-20个）
          ↓ HAS_MODULE 关系
        E_module 实体（每卷 ≤8 个）
          ↓ T_main 关系（模块间时序）
        E_module → E_module

    Attributes:
        t_main_volumes: T_main 实体列表（剧情卷，5-20 个）
        e_modules: E_module 实体列表（每卷 ≤8 个）
        t_main_relations: T_main → T_main 关系（卷间时序，纯索引）
        has_module_relations: T_main → E_module 关系（归属）
        t_main_module_relations: E_module → E_module 关系（模块间时序）
    """
    t_main_volumes: list[Entity] = field(default_factory=list)
    e_modules: list[Entity] = field(default_factory=list)
    t_main_relations: list[Relation] = field(default_factory=list)
    has_module_relations: list[Relation] = field(default_factory=list)
    t_main_module_relations: list[Relation] = field(default_factory=list)


def _build_module_entities_and_relations(
    t_main_volumes: list[Entity],
    volume_modules: list[list[dict]],
) -> tuple[list[Entity], list[Relation], list[Relation]]:
    """构建 E_module 实体、HAS_MODULE 关系和模块间时序关系。

    Args:
        t_main_volumes: T_main 卷实体列表
        volume_modules: 每卷的 E_module 候选列表，外层索引对应卷索引

    Returns:
        (e_modules, has_module_relations, t_main_module_relations) 三元组
    """
    e_modules: list[Entity] = []
    has_module_relations: list[Relation] = []
    t_main_module_relations: list[Relation] = []

    for vol_idx, (vol, mods) in enumerate(zip(t_main_volumes, volume_modules)):
        mod_entities: list[Entity] = []
        for m_idx, mod in enumerate(mods):
            mod_id = mod.get("id") or f"E_module_{vol_idx}_{m_idx}"
            mod_entity = Entity(
                id=mod_id,
                name=mod.get("name", f"剧情模块_{vol_idx + 1}_{m_idx + 1}"),
                type="E_module",
                coords={"T": mod_id},
                base_info={
                    "start_chunk": mod.get("start_chunk", 0),
                    "end_chunk": mod.get("end_chunk", 0),
                    "theme": mod.get("theme", ""),
                    "parent_volume": vol.id,
                },
            )
            mod_entities.append(mod_entity)
            e_modules.append(mod_entity)

            has_module_relations.append(Relation(
                source_id=vol.id,
                target_id=mod_id,
                relation_type="HAS_MODULE",
                strength="strong",
            ))

        for k in range(len(mod_entities) - 1):
            t_main_module_relations.append(Relation(
                source_id=mod_entities[k].id,
                target_id=mod_entities[k + 1].id,
                relation_type="T_main",
                strength="strong",
            ))

    return e_modules, has_module_relations, t_main_module_relations


def build_skeleton_incremental(cluster_results: dict[str, Any]) -> Skeleton:
    """增量模式构建时序骨架。

    将 cluster_summaries() 输出的聚类结果转换为 Skeleton 结构。
    自动保证:
    - T_main 卷数 ∈ [5, 20]（不足 5 个扩展，超过 20 个合并）
    - 每卷 E_module ≤8 个（超过 8 个合并相邻模块）

    Args:
        cluster_results: cluster_summaries() 输出，含字段::
            - t_main_candidates: list[dict] — [{id, name, range, start_chunk, end_chunk, theme, stage}]
            - module_candidates: list[dict] — [{id, name, range, start_chunk, end_chunk, theme, stage}]

    Returns:
        Skeleton 实例，含三层实体结构和五类关系

    Raises:
        ValueError: cluster_results 为空或 t_main_candidates 为空时抛出

    Example:
        >>> results = cluster_summaries(summaries, use_embedding=False)
        >>> skeleton = build_skeleton_incremental(results)
        >>> 5 <= len(skeleton.t_main_volumes) <= 20
        True
    """
    t_main_candidates = cluster_results.get("t_main_candidates", [])
    module_candidates = cluster_results.get("module_candidates", [])

    if not t_main_candidates:
        raise ValueError(
            "cluster_results.t_main_candidates 为空，无法构建时序骨架"
        )

    # ─── Step 1: 调整 T_main 卷数至 [5, 20] ──────────────────
    adjusted_t_main = _adjust_volume_count(t_main_candidates)

    # ─── Step 2: 构建 T_main 实体 ───────────────────────────
    t_main_volumes: list[Entity] = []
    for i, cand in enumerate(adjusted_t_main):
        vol_id = f"T_main_vol_{i}"
        vol = Entity(
            id=vol_id,
            name=cand.get("name", f"剧情卷_{i + 1}"),
            type="T_main",
            coords={"T": vol_id},
            base_info={
                "start_chunk": cand.get("start_chunk", 0),
                "end_chunk": cand.get("end_chunk", 0),
                "theme": cand.get("theme", ""),
                "stage": cand.get("stage", "发展"),
                "range": cand.get("range", [0, 0]),
            },
        )
        t_main_volumes.append(vol)

    # ─── Step 3: 构建 T_main → T_main 卷间时序关系 ─────────
    t_main_relations = _build_volume_chain(t_main_volumes)

    # ─── Step 4: 分配 E_module 到 T_main 卷（≤8/卷）─────────
    volume_modules = _assign_modules_to_volumes(adjusted_t_main, module_candidates)

    # ─── Step 5: 构建 E_module 实体 + HAS_MODULE 关系 + 模块间时序 ───
    e_modules, has_module_relations, t_main_module_relations = _build_module_entities_and_relations(
        t_main_volumes, volume_modules
    )

    skeleton = Skeleton(
        t_main_volumes=t_main_volumes,
        e_modules=e_modules,
        t_main_relations=t_main_relations,
        has_module_relations=has_module_relations,
        t_main_module_relations=t_main_module_relations,
    )

    logger.info(
        f"时序骨架构建完成(增量模式): {len(t_main_volumes)} 卷, "
        f"{len(e_modules)} 个 E_module, "
        f"{len(t_main_relations)} 卷间关系, "
        f"{len(has_module_relations)} 归属关系, "
        f"{len(t_main_module_relations)} 模块间关系"
    )
    return skeleton


def adjust_skeleton(existing: Skeleton, new_cluster: dict[str, Any]) -> Skeleton:
    """动态调整时序骨架。

    将新 cluster 的候选合并到已有 Skeleton 中，保持 T_main 链无断裂。
    调整规则:
    - 追加新 T_main 候选至 existing.t_main_volumes 末尾
    - 若总数超过 20，合并相邻卷
    - 重新分配新 E_module 候选至对应卷
    - 重建 T_main 链保证连续性

    Args:
        existing: 已有 Skeleton 实例
        new_cluster: 新 cluster_summaries() 输出

    Returns:
        调整后的新 Skeleton 实例（不修改原 existing）
    """
    new_t_main_candidates = new_cluster.get("t_main_candidates", [])
    new_module_candidates = new_cluster.get("module_candidates", [])

    # ─── Step 1: 合并 T_main 候选 ───────────────────────────
    existing_candidates = [
        {
            "id": vol.id,
            "name": vol.name,
            "start_chunk": vol.base_info.get("start_chunk", 0),
            "end_chunk": vol.base_info.get("end_chunk", 0),
            "range": vol.base_info.get("range", [0, 0]),
            "theme": vol.base_info.get("theme", ""),
            "stage": vol.base_info.get("stage", "发展"),
        }
        for vol in existing.t_main_volumes
    ]
    merged_candidates = existing_candidates + new_t_main_candidates

    # 按 start_chunk 排序
    merged_candidates.sort(key=lambda c: c.get("start_chunk", 0))

    # ─── Step 2: 调整卷数至 [5, 20] ─────────────────────────
    adjusted_t_main = _adjust_volume_count(merged_candidates)

    # ─── Step 3: 合并 E_module 候选 ─────────────────────────
    existing_modules = [
        {
            "id": mod.id,
            "name": mod.name,
            "start_chunk": mod.base_info.get("start_chunk", 0),
            "end_chunk": mod.base_info.get("end_chunk", 0),
            "theme": mod.base_info.get("theme", ""),
            "stage": "",
        }
        for mod in existing.e_modules
    ]
    merged_modules = existing_modules + new_module_candidates
    merged_modules.sort(key=lambda m: m.get("start_chunk", 0))

    # ─── Step 4: 重建 Skeleton ──────────────────────────────
    # 复用 build_skeleton_incremental 的核心逻辑
    # 保留 existing 候选的原 ID（如有），新候选使用默认 ID
    t_main_volumes: list[Entity] = []
    for i, cand in enumerate(adjusted_t_main):
        vol_id = cand.get("id") or f"T_main_vol_{i}"
        vol = Entity(
            id=vol_id,
            name=cand.get("name", f"剧情卷_{i + 1}"),
            type="T_main",
            coords={"T": vol_id},
            base_info={
                "start_chunk": cand.get("start_chunk", 0),
                "end_chunk": cand.get("end_chunk", 0),
                "theme": cand.get("theme", ""),
                "stage": cand.get("stage", "发展"),
                "range": cand.get("range", [0, 0]),
            },
        )
        t_main_volumes.append(vol)

    t_main_relations = _build_volume_chain(t_main_volumes)
    volume_modules = _assign_modules_to_volumes(adjusted_t_main, merged_modules)

    e_modules, has_module_relations, t_main_module_relations = _build_module_entities_and_relations(
        t_main_volumes, volume_modules
    )

    adjusted = Skeleton(
        t_main_volumes=t_main_volumes,
        e_modules=e_modules,
        t_main_relations=t_main_relations,
        has_module_relations=has_module_relations,
        t_main_module_relations=t_main_module_relations,
    )

    logger.info(
        f"时序骨架动态调整完成: {len(t_main_volumes)} 卷, "
        f"{len(e_modules)} 个 E_module"
    )
    return adjusted


def finalize_skeleton(skeleton: Skeleton) -> Skeleton:
    """全书完成后稳定化时序骨架。

    检查并修复 T_main 链的连续性，确保:
    - T_main 卷数 ∈ [5, 20]
    - 卷间关系数 = 卷数 - 1（无断裂）
    - 每卷 E_module ≤8 个

    Args:
        skeleton: 待稳定化的 Skeleton 实例

    Returns:
        稳定化后的 Skeleton 实例（如无问题则原样返回）
    """
    # 重建 T_main 链以保证连续性
    t_main_relations = _build_volume_chain(skeleton.t_main_volumes)

    # 检查 E_module 数量是否需要合并
    needs_rebuild = False
    volume_module_count: dict[str, int] = {}
    for rel in skeleton.has_module_relations:
        volume_module_count[rel.source_id] = volume_module_count.get(rel.source_id, 0) + 1

    for count in volume_module_count.values():
        if count > MAX_E_MODULES_PER_VOLUME:
            needs_rebuild = True
            break

    if not needs_rebuild and len(t_main_relations) == len(skeleton.t_main_relations):
        # 无需修复，仅更新 t_main_relations（保证连续性）
        return Skeleton(
            t_main_volumes=skeleton.t_main_volumes,
            e_modules=skeleton.e_modules,
            t_main_relations=t_main_relations,
            has_module_relations=skeleton.has_module_relations,
            t_main_module_relations=skeleton.t_main_module_relations,
        )

    # 重建：合并 E_module 候选
    logger.info("finalize_skeleton: 检测到需重建 E_module 归属")
    # 重建 module_candidates
    module_candidates = [
        {
            "id": mod.id,
            "name": mod.name,
            "start_chunk": mod.base_info.get("start_chunk", 0),
            "end_chunk": mod.base_info.get("end_chunk", 0),
            "theme": mod.base_info.get("theme", ""),
            "stage": "",
        }
        for mod in skeleton.e_modules
    ]
    module_candidates.sort(key=lambda m: m.get("start_chunk", 0))

    volume_candidates = [
        {
            "id": vol.id,
            "name": vol.name,
            "start_chunk": vol.base_info.get("start_chunk", 0),
            "end_chunk": vol.base_info.get("end_chunk", 0),
            "range": vol.base_info.get("range", [0, 0]),
            "theme": vol.base_info.get("theme", ""),
            "stage": vol.base_info.get("stage", "发展"),
        }
        for vol in skeleton.t_main_volumes
    ]

    volume_modules = _assign_modules_to_volumes(volume_candidates, module_candidates)

    e_modules, has_module_relations, t_main_module_relations = _build_module_entities_and_relations(
        skeleton.t_main_volumes, volume_modules
    )

    return Skeleton(
        t_main_volumes=skeleton.t_main_volumes,
        e_modules=e_modules,
        t_main_relations=t_main_relations,
        has_module_relations=has_module_relations,
        t_main_module_relations=t_main_module_relations,
    )


# ─── 内部工具函数 ─────────────────────────────────────────

def _adjust_volume_count(candidates: list[dict]) -> list[dict]:
    """调整 T_main 卷候选数量至 [MIN_T_MAIN_VOLUMES, MAX_T_MAIN_VOLUMES]。

    - 不足 5 个: 均匀切分现有候选扩展至 5 个
    - 超过 20 个: 合并相邻候选至 20 个
    - 5-20 个: 原样返回
    """
    count = len(candidates)
    if count == 0:
        return []

    if count < MIN_T_MAIN_VOLUMES:
        # 扩展：均匀切分
        return _expand_candidates(candidates, MIN_T_MAIN_VOLUMES)
    if count > MAX_T_MAIN_VOLUMES:
        # 合并：相邻归并
        return _merge_candidates(candidates, MAX_T_MAIN_VOLUMES)
    return candidates


def _expand_candidates(candidates: list[dict], target: int) -> list[dict]:
    """均匀切分现有候选至 target 个。"""
    if not candidates:
        return []

    expanded: list[dict] = []
    # 计算总 chunk 范围
    all_starts = [c.get("start_chunk", 0) for c in candidates]
    all_ends = [c.get("end_chunk", 0) for c in candidates]
    min_start = min(all_starts) if all_starts else 0
    max_end = max(all_ends) if all_ends else 0
    total_chunks = max(max_end - min_start + 1, target)
    chunk_per_volume = max(1, total_chunks // target)

    for i in range(target):
        start = min_start + i * chunk_per_volume
        end = start + chunk_per_volume - 1 if i < target - 1 else max_end
        # 从原候选中继承主题（按比例分配）
        source_idx = min(i * len(candidates) // target, len(candidates) - 1)
        source = candidates[source_idx]
        expanded.append({
            "id": f"T_main_vol_{i}",
            "name": f"剧情卷_{i + 1}",
            "start_chunk": start,
            "end_chunk": end,
            "range": [start, end],
            "theme": source.get("theme", f"主题_{i}"),
            "stage": _infer_stage(i, target),
        })
    return expanded


def _merge_candidates(candidates: list[dict], target: int) -> list[dict]:
    """合并相邻候选至 target 个。"""
    if len(candidates) <= target:
        return candidates

    # 按 start_chunk 排序
    sorted_cands = sorted(candidates, key=lambda c: c.get("start_chunk", 0))
    # 计算每组的大小
    group_size = len(sorted_cands) / target
    merged: list[dict] = []

    for i in range(target):
        start_idx = int(i * group_size)
        end_idx = int((i + 1) * group_size) if i < target - 1 else len(sorted_cands)
        group = sorted_cands[start_idx:end_idx]
        if not group:
            continue
        merged.append({
            "id": f"T_main_vol_{i}",
            "name": f"剧情卷_{i + 1}",
            "start_chunk": group[0].get("start_chunk", 0),
            "end_chunk": group[-1].get("end_chunk", 0),
            "range": [group[0].get("start_chunk", 0), group[-1].get("end_chunk", 0)],
            "theme": group[0].get("theme", f"主题_{i}"),
            "stage": _infer_stage(i, target),
        })
    return merged


def _infer_stage(volume_index: int, total_volumes: int) -> str:
    """推断卷的阶段定位。"""
    if total_volumes <= 0:
        return "发展"
    ratio = volume_index / max(total_volumes, 1)
    if ratio < 0.15:
        return "开篇"
    if ratio < 0.40:
        return "发展"
    if ratio < 0.60:
        return "转折"
    if ratio < 0.80:
        return "高潮"
    if ratio < 0.95:
        return "收束"
    return "尾声"


def _build_volume_chain(volumes: list[Entity]) -> list[Relation]:
    """构建 T_main 卷间时序关系链。"""
    relations: list[Relation] = []
    for i in range(len(volumes) - 1):
        relations.append(Relation(
            source_id=volumes[i].id,
            target_id=volumes[i + 1].id,
            relation_type="T_main",
            strength="strong",
        ))
    return relations


def _assign_modules_to_volumes(
    volumes: list[dict],
    modules: list[dict],
) -> list[list[dict]]:
    """将 E_module 候选分配到 T_main 卷（每卷 ≤8 个，超过则合并）。

    Args:
        volumes: T_main 卷候选列表
        modules: E_module 候选列表

    Returns:
        二维列表，外层索引对应卷索引，内层为该卷的 E_module 列表
    """
    if not volumes:
        return []

    # 初始化每卷的模块列表
    volume_modules: list[list[dict]] = [[] for _ in volumes]

    # 按 start_chunk 排序模块
    sorted_modules = sorted(modules, key=lambda m: m.get("start_chunk", 0))

    for mod in sorted_modules:
        mod_start = mod.get("start_chunk", 0)
        mod_end = mod.get("end_chunk", 0)
        mod_mid = (mod_start + mod_end) / 2

        # 找到模块中点落在哪个卷的范围
        assigned_idx = -1
        for i, vol in enumerate(volumes):
            vol_start = vol.get("start_chunk", 0)
            vol_end = vol.get("end_chunk", 0)
            if vol_start <= mod_mid <= vol_end:
                assigned_idx = i
                break

        # 若中点不在任何卷范围，找最近的卷
        if assigned_idx == -1:
            min_dist = float("inf")
            for i, vol in enumerate(volumes):
                vol_start = vol.get("start_chunk", 0)
                vol_end = vol.get("end_chunk", 0)
                vol_mid = (vol_start + vol_end) / 2
                dist = abs(mod_mid - vol_mid)
                if dist < min_dist:
                    min_dist = dist
                    assigned_idx = i

        if assigned_idx >= 0:
            volume_modules[assigned_idx].append(mod)

    # 合并超过 8 个的卷
    for i, mods in enumerate(volume_modules):
        if len(mods) > MAX_E_MODULES_PER_VOLUME:
            volume_modules[i] = _merge_modules(mods, MAX_E_MODULES_PER_VOLUME)

    return volume_modules


def _merge_modules(modules: list[dict], target: int) -> list[dict]:
    """合并相邻 E_module 至 target 个。"""
    if len(modules) <= target:
        return modules

    sorted_mods = sorted(modules, key=lambda m: m.get("start_chunk", 0))
    group_size = len(sorted_mods) / target
    merged: list[dict] = []

    for i in range(target):
        start_idx = int(i * group_size)
        end_idx = int((i + 1) * group_size) if i < target - 1 else len(sorted_mods)
        group = sorted_mods[start_idx:end_idx]
        if not group:
            continue
        merged.append({
            "id": f"E_module_merged_{i}",
            "name": f"剧情模块_{i + 1}",
            "start_chunk": group[0].get("start_chunk", 0),
            "end_chunk": group[-1].get("end_chunk", 0),
            "range": [group[0].get("start_chunk", 0), group[-1].get("end_chunk", 0)],
            "theme": group[0].get("theme", f"子主题_{i}"),
            "stage": "",
        })
    return merged
