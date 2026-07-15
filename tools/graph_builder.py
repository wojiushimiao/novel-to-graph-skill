#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 图构建器

锚定: L2_数据模型与核心算法.md §2.11
      L3_接口契约与约束.md §1.3.7

从实体和关系构建 NetworkX 有向图。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    nx = None
    _HAS_NETWORKX = False

try:
    from .models import STRENGTH_WEIGHT_MAP
except ImportError:
    from models import STRENGTH_WEIGHT_MAP

if TYPE_CHECKING:
    from .models import Entity, Relation
    from .timeline_skeleton_builder import Skeleton

logger = logging.getLogger(__name__)


def build(
    entities: "list[Entity]",
    relations: "list[Relation]",
):
    """从实体和关系构建 NetworkX 有向图。

    节点属性: node_type, label, base_info, detail_info, coords
    边属性: relation_type, strength, weight, description

    Args:
        entities: 实体列表
        relations: 关系列表

    Returns:
        nx.DiGraph
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装，无法构建图")

    G = nx.DiGraph()

    # 添加节点
    for entity in entities:
        G.add_node(
            entity.id,
            node_type=entity.type,
            label=entity.name,
            base_info=entity.base_info,
            detail_info=entity.detail_info,
            coords=entity.coords,
            source_chapter=entity.source_chapter,
            char_offset=entity.char_offset,
        )

    # 添加边
    added_edges = 0
    for rel in relations:
        if rel.source_id in G and rel.target_id in G:
            weight = STRENGTH_WEIGHT_MAP.get(rel.strength, 0.5)
            G.add_edge(
                rel.source_id,
                rel.target_id,
                relation_type=rel.relation_type,
                strength=rel.strength,
                weight=weight,
                description=rel.description,
                source_chapter=rel.source_chapter,
            )
            added_edges += 1
        else:
            logger.debug(
                f"边跳过（端点不存在）: {rel.source_id}→{rel.target_id}"
            )

    logger.info(
        f"图构建完成: {G.number_of_nodes()} 节点, {G.number_of_edges()} 边 "
        f"(输入: {len(entities)} 实体, {len(relations)} 关系, 成功添加 {added_edges} 边)"
    )
    return G


def build_evolves_to_relations(
    entities: "list[Entity]",
) -> "list[Relation]":
    """构建人物弧光关系链（v0.5.0 A3）。

    按角色名称分组 character 类型实体，按 T_main 卷索引排序，
    相邻实体间创建 evolves_to 关系。

    Args:
        entities: 所有实体列表

    Returns:
        evolves_to 关系列表（可能为空）

    Contract:
        - 仅处理 type == "character" 的实体
        - 关系 strength 固定为 "strong"
        - 关系 description 格式: "角色弧光: {name} 从第{i}卷到第{i+1}卷的演化"
    """
    import re
    from .models import MULTI_PROFILE_TYPES, Relation

    # 筛选角色实体
    character_entities = [e for e in entities if e.type in MULTI_PROFILE_TYPES]

    if not character_entities:
        return []

    # 按角色名称分组
    # 从 id 格式 "C_{name}__T_main_vol_{idx}" 中提取 name 和 idx
    groups: dict[str, list[tuple[int, "Entity"]]] = {}
    id_pattern = re.compile(r"^[A-Z]_(.+?)__T_main_vol_(\d+)$")

    for ent in character_entities:
        m = id_pattern.match(ent.id)
        if m:
            name = m.group(1)
            vol_idx = int(m.group(2))
            groups.setdefault(name, []).append((vol_idx, ent))
        else:
            # 旧格式 id: "C_{name}"，无卷索引，跳过
            pass

    # 构建 evolves_to 关系
    relations: "list[Relation]" = []
    for name, entries in groups.items():
        if len(entries) < 2:
            continue
        # 按卷索引排序
        entries.sort(key=lambda x: x[0])
        for i in range(len(entries) - 1):
            vol_i, ent_i = entries[i]
            vol_j, ent_j = entries[i + 1]
            relations.append(Relation(
                source_id=ent_i.id,
                target_id=ent_j.id,
                relation_type="evolves_to",
                strength="strong",
                description=f"角色弧光: {name} 从第{vol_i}卷到第{vol_j}卷的演化",
            ))

    return relations


def from_db(db_path: str):
    """从 SQLite 数据库加载图。

    Args:
        db_path: SQLite 数据库文件路径

    Returns:
        nx.DiGraph
    """
    import sqlite3
    from pathlib import Path

    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    conn = sqlite3.connect(str(Path(db_path)))
    conn.row_factory = sqlite3.Row

    G = nx.DiGraph()

    # 加载实体
    for row in conn.execute(
        "SELECT id, name, type, base_info, detail_info, coords, source_chapter, char_offset FROM entities"
    ):
        G.add_node(
            row["id"],
            node_type=row["type"],
            label=row["name"],
            base_info=_safe_json_load(row["base_info"]),
            detail_info=_safe_json_load(row["detail_info"]),
            coords=_safe_json_load(row["coords"]),
            source_chapter=row["source_chapter"] or "",
            char_offset=row["char_offset"] or 0,
        )

    # 加载关系
    for row in conn.execute(
        "SELECT source_id, target_id, relation_type, strength, description, source_chapter FROM wiki_relations"
    ):
        src, tgt = row["source_id"], row["target_id"]
        if src in G and tgt in G:
            weight = STRENGTH_WEIGHT_MAP.get(row["strength"], 0.5)
            G.add_edge(
                src, tgt,
                relation_type=row["relation_type"],
                strength=row["strength"],
                weight=weight,
                description=row["description"] or "",
                source_chapter=row["source_chapter"] or "",
            )

    conn.close()
    logger.info(f"从DB加载图: {G.number_of_nodes()} 节点, {G.number_of_edges()} 边")
    return G


def _safe_json_load(value):
    """安全 JSON 解析。"""
    if value is None:
        return {}
    if isinstance(value, str):
        import json
        try:
            return json.loads(value) if value else {}
        except json.JSONDecodeError:
            return {}
    return value


# v0.5.1 B1: 骨架质量评估阈值
SKELETON_QUALITY = {
    "t_main_min": 5,
    "t_main_ideal_min": 8,
    "t_main_ideal_max": 15,
    "t_main_max": 20,
    "modules_per_vol_min": 2,
    "modules_per_vol_ideal": 4,
    "modules_per_vol_max": 8,
    "t_branch_coverage_min": 0.6,
}

# v0.5.1 B1: 骨架重做阈值（提高阈值 = 更多边界 = 更细颗粒度）
# 注意: 代码使用 sim < threshold 触发边界，因此提高阈值产生更多聚类
REBUILD_THRESHOLDS = {
    "temporal": 0.70,  # 原 0.55 → 提高，更多卷边界
    "scene": 0.85,     # 原 0.70 → 提高，更多模块边界
    "entity": 0.80,    # 原 0.65 → 提高，更多模块边界
}


def evaluate_skeleton_quality(
    skeleton: "Skeleton",
    entities: "list[Entity]",
    relations: "list[Relation]",
) -> dict[str, Any]:
    """评估时序骨架质量（v0.5.1 B1）。

    评估三个维度：
    1. T_main 卷数: 理想 8-15，<5 为差
    2. E_module/卷: 理想 4-6，<2 为过粗
    3. T_branch 覆盖率: 每个 E_module 应有 ≥3 个 E_event 挂载

    Args:
        skeleton: S2.5 产出的骨架
        entities: DB 中所有实体
        relations: DB 中所有关系

    Returns:
        {
            "verdict": "pass" | "rebuild",
            "t_main_count": int,
            "avg_modules_per_vol": float,
            "t_branch_coverage": float,
            "issues": list[str],
        }
    """
    # ─── 维度1: T_main 卷数 ─────────────────────────────────
    t_main_count = len(skeleton.t_main_volumes)

    # 边界: 空骨架直接返回
    if t_main_count == 0:
        return {
            "verdict": "rebuild",
            "t_main_count": 0,
            "avg_modules_per_vol": 0.0,
            "t_branch_coverage": 0.0,
            "issues": ["骨架为空"],
        }

    # ─── 维度2: E_module 颗粒度（每卷平均模块数）────────────
    avg_modules_per_vol = len(skeleton.e_modules) / max(t_main_count, 1)

    # ─── 维度3: T_branch 覆盖率 ─────────────────────────────
    # 统计 skeleton.e_modules 中 type == "E_module" 的实体
    e_module_entities = [e for e in skeleton.e_modules if e.type == "E_module"]
    total_e_modules = len(e_module_entities)

    if total_e_modules == 0:
        t_branch_coverage = 0.0
    else:
        # 统计每个 E_module 的 T_branch 入边数（target_id == e_module.id）
        e_module_ids = {e.id for e in e_module_entities}
        t_branch_counts: dict[str, int] = {}
        for rel in relations:
            if rel.relation_type == "T_branch" and rel.target_id in e_module_ids:
                t_branch_counts[rel.target_id] = t_branch_counts.get(rel.target_id, 0) + 1

        # 覆盖: T_branch 入边 ≥3
        covered_count = sum(
            1 for e in e_module_entities if t_branch_counts.get(e.id, 0) >= 3
        )
        t_branch_coverage = covered_count / total_e_modules

    # ─── 综合裁决 ───────────────────────────────────────────
    issues: list[str] = []
    if t_main_count < SKELETON_QUALITY["t_main_min"]:
        issues.append("T_main 卷数过少")
    if avg_modules_per_vol < SKELETON_QUALITY["modules_per_vol_min"]:
        issues.append("E_module 颗粒度过粗")
    if t_branch_coverage < SKELETON_QUALITY["t_branch_coverage_min"]:
        issues.append("T_branch 覆盖率不足")

    verdict = "rebuild" if issues else "pass"

    return {
        "verdict": verdict,
        "t_main_count": t_main_count,
        "avg_modules_per_vol": avg_modules_per_vol,
        "t_branch_coverage": t_branch_coverage,
        "issues": issues,
    }


def rebuild_skeleton(
    summaries: list[dict],
    adjusted_thresholds: dict[str, float] | None = None,
    original_skeleton: "Skeleton | None" = None,
) -> "Skeleton":
    """用调整后阈值重建骨架（v0.5.1 B1）。

    使用更高的聚类阈值重新聚类，产生更多 T_main 卷和更细的 E_module 颗粒度。
    重做失败时返回原始骨架，不抛异常。

    Args:
        summaries: 原始摘要列表（来自 SummaryBuffer）
        adjusted_thresholds: 聚类阈值，默认 REBUILD_THRESHOLDS
        original_skeleton: 原始骨架（降级时返回）

    Returns:
        新 Skeleton 或原始 Skeleton（降级）
    """
    # Lazy imports to avoid circular dependencies
    try:
        from .timeline_skeleton_builder import Skeleton, build_skeleton_incremental
        from .semantic_clusterer import cluster_summaries
    except ImportError:
        from timeline_skeleton_builder import Skeleton, build_skeleton_incremental
        from semantic_clusterer import cluster_summaries

    if adjusted_thresholds is None:
        adjusted_thresholds = REBUILD_THRESHOLDS

    if original_skeleton is None:
        original_skeleton = Skeleton()

    if not summaries:
        logger.warning("骨架重做跳过: summaries 为空，返回原始骨架")
        return original_skeleton

    try:
        cluster_results = cluster_summaries(summaries, thresholds=adjusted_thresholds)
        new_skeleton = build_skeleton_incremental(cluster_results)
        return new_skeleton
    except Exception as e:
        logger.warning(f"骨架重做失败: {e}")
        return original_skeleton
