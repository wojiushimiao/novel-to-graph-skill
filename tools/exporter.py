#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 导出器

锚定: L2_数据模型与核心算法.md §2.18
      L3_接口契约与约束.md §1.4.7 / 1.4.8

导出 Markdown 实体档案和 JSON node-link 格式。
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Entity, Relation

logger = logging.getLogger(__name__)


def to_markdown(
    graph,
    entities: "list[Entity]",
    relations: "list[Relation]",
    stats: dict,
    title: str = "",
    group_by_character: bool = False,
) -> str:
    """生成 Markdown 格式实体档案。

    Args:
        graph: nx.DiGraph
        entities: 实体列表
        relations: 关系列表
        stats: 统计报告
        title: 标题
        group_by_character: v0.5.0 A3: 按角色聚合多卷档案

    Returns:
        Markdown 字符串
    """
    # 按类型分组实体
    by_type: dict[str, list] = defaultdict(list)
    for e in entities:
        by_type[e.type].append(e)

    # 构建关系索引: source_id -> [relation]
    rel_index: dict[str, list] = defaultdict(list)
    for r in relations:
        rel_index[r.source_id].append(r)

    # 实体ID -> label 映射
    id_to_label = {e.id: e.name for e in entities}

    type_labels = {
        "character": "角色",
        "location": "地点",
        "event": "事件",
        "item": "物品",
        "rule": "规则",
        "system": "系统",
    }

    lines: list[str] = []
    lines.append(f"# 《{title or '小说'}》实体档案\n")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**总实体**: {stats.get('node_count', len(entities))} | "
                 f"**总关系**: {stats.get('edge_count', len(relations))} | "
                 f"**图密度**: {stats.get('density', 0)}\n")
    lines.append("---\n")

    # v0.5.0 A3: 按角色聚合多卷档案
    if group_by_character:
        # 从角色 id "C_{name}__T_main_vol_{idx}" 中提取基础名称
        char_groups: dict[str, list] = defaultdict(list)
        char_pattern = re.compile(r"^C_(.+?)__T_main_vol_\d+$")
        for e in entities:
            if e.type == "character":
                m = char_pattern.match(e.id)
                base_name = m.group(1) if m else e.name
                char_groups[base_name].append(e)

        lines.append("## 人物弧光总览\n")
        for base_name, char_ents in sorted(char_groups.items()):
            # 按卷索引排序
            vol_pattern = re.compile(r"__T_main_vol_(\d+)$")
            char_ents.sort(key=lambda e: int(vol_pattern.search(e.id).group(1)) if vol_pattern.search(e.id) else 0)
            lines.append(f"### {base_name} ({len(char_ents)}卷)\n")
            lines.append("| 卷 | 档案 |")
            lines.append("|----|------|")
            for ent in char_ents:
                vol_match = vol_pattern.search(ent.id)
                vol_label = f"第{vol_match.group(1)}卷" if vol_match else "未知"
                info_preview = ent.info[:80].replace("\n", " ") if ent.info else "(无)"
                lines.append(f"| {vol_label} | {info_preview} |")
            lines.append("")

    # 按类型顺序输出
    type_order = ["character", "location", "event", "item", "rule", "system", "monster", "knowledge"]
    for etype in type_order:
        ents = by_type.get(etype, [])
        if not ents:
            continue
        label = type_labels.get(etype, etype)
        lines.append(f"## {label} ({len(ents)}个)\n")

        for entity in ents:
            lines.append(f"### {entity.name}\n")
            base_info = entity.base_info or {}
            if base_info.get("first_appearance"):
                lines.append(f"- **首次出现**: {base_info['first_appearance']}")
            aliases = base_info.get("aliases", [])
            if aliases:
                lines.append(f"- **别名**: {', '.join(aliases) if isinstance(aliases, list) else aliases}")
            if base_info.get("entity_description"):
                lines.append(f"- **描述**: {base_info['entity_description']}")
            if entity.source_chapter:
                lines.append(f"- **首次章节**: {entity.source_chapter}")

            # 关系
            rels = rel_index.get(entity.id, [])
            if rels:
                lines.append("\n**关系**:\n")
                lines.append("| 关系类型 | 目标 | 强度 | 描述 |")
                lines.append("|---------|------|------|------|")
                for rel in rels:
                    target_label = id_to_label.get(rel.target_id, rel.target_id)
                    lines.append(
                        f"| {rel.relation_type} | {target_label} | {rel.strength} | {rel.description} |"
                    )
            lines.append("")

    # 图统计
    lines.append("## 图统计\n")
    lines.append(f"- 总实体: {stats.get('node_count', 0)}")
    lines.append(f"- 总关系: {stats.get('edge_count', 0)}")
    lines.append(f"- 图密度: {stats.get('density', 0)}")
    lines.append(f"- 平均度: {stats.get('avg_degree', 0)}")
    lines.append(f"- 孤立实体: {stats.get('isolated_count', 0)}")

    type_dist = stats.get("type_distribution", {})
    if type_dist:
        lines.append("\n**实体类型分布**:\n")
        lines.append("| 类型 | 数量 |")
        lines.append("|------|------|")
        for t, c in sorted(type_dist.items(), key=lambda x: -x[1]):
            lines.append(f"| {type_labels.get(t, t)} | {c} |")

    rel_dist = stats.get("relation_type_distribution", {})
    if rel_dist:
        lines.append("\n**关系类型分布**:\n")
        lines.append("| 关系类型 | 数量 |")
        lines.append("|---------|------|")
        for t, c in sorted(rel_dist.items(), key=lambda x: -x[1]):
            lines.append(f"| {t} | {c} |")

    logger.info(f"Markdown 导出完成: {len(entities)} 实体, {len(relations)} 关系")
    return "\n".join(lines)


def to_json(
    graph,
    entities: "list[Entity]",
    relations: "list[Relation]",
    stats: dict,
    analysis: dict,
    title: str = "",
) -> str:
    """生成 JSON 格式导出（node-link 格式）。

    Args:
        graph: nx.DiGraph
        entities: 实体列表
        relations: 关系列表
        stats: 统计报告
        analysis: 分析结果
        title: 标题

    Returns:
        JSON 字符串
    """
    # 节点
    nodes = []
    for e in entities:
        nodes.append({
            "id": e.id,
            "label": e.name,
            "type": e.type,
            "base_info": e.base_info,
            "detail_info": e.detail_info,
            "stitch_tags": e.stitch_tags,
            "coords": e.coords,
            "source_chapter": e.source_chapter,
            "importance_score": (e.base_info or {}).get("importance_score", 0.0),
            "degree_centrality": analysis.get("degree", {}).get(e.id, 0.0),
            "betweenness_centrality": analysis.get("betweenness", {}).get(e.id, 0.0),
            "community": _get_community(e.id, analysis.get("communities", {})),
        })

    # 边
    edges = []
    for i, r in enumerate(relations):
        edges.append({
            "id": f"e_{i:04d}",
            "source": r.source_id,
            "target": r.target_id,
            "relation_type": r.relation_type,
            "strength": r.strength,
            "description": r.description,
            "source_chapter": r.source_chapter,
        })

    # 社群
    communities = {}
    for cid, node_ids in analysis.get("communities", {}).items():
        communities[str(cid)] = {
            "name": f"社群{cid + 1}",
            "node_ids": node_ids,
            "node_count": len(node_ids),
        }

    data = {
        "title": title or "小说分析导出",
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "nodes": nodes,
        "edges": edges,
        "communities": communities,
        "bridges": analysis.get("bridges", []),
        "orphans": [
            {"id": nid, "label": graph.nodes[nid].get("label", nid) if nid in graph else nid}
            for nid in analysis.get("orphans", [])
        ],
    }

    logger.info(f"JSON 导出完成: {len(nodes)} 节点, {len(edges)} 边")
    return json.dumps(data, ensure_ascii=False, indent=2)


def _get_community(node_id: str, communities: dict) -> int:
    """查找节点所属社群。"""
    for cid, nodes in communities.items():
        if node_id in nodes:
            return cid
    return -1
