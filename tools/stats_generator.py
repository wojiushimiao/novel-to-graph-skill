#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 统计报告生成器

锚定: L2_数据模型与核心算法.md §2.16
      L3_接口契约与约束.md §1.4.5

生成图统计报告。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    nx = None
    _HAS_NETWORKX = False

if TYPE_CHECKING:
    from .models import Entity, Relation

logger = logging.getLogger(__name__)


def generate(
    graph,
    entities: "list[Entity]",
    relations: "list[Relation]",
) -> dict:
    """生成图统计报告。

    Args:
        graph: nx.DiGraph
        entities: 实体列表
        relations: 关系列表

    Returns:
        {
            "node_count": int,
            "edge_count": int,
            "type_distribution": {type: count},
            "relation_type_distribution": {rel_type: count},
            "density": float,
            "avg_degree": float,
            "isolated_count": int,
        }
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    # 实体类型分布
    type_dist: dict[str, int] = defaultdict(int)
    for entity in entities:
        type_dist[entity.type] += 1

    # 关系类型分布
    rel_dist: dict[str, int] = defaultdict(int)
    for rel in relations:
        rel_dist[rel.relation_type] += 1

    # 图密度
    if node_count > 1:
        density = 2 * edge_count / (node_count * (node_count - 1))
    else:
        density = 0.0

    # 平均度
    avg_degree = 2 * edge_count / node_count if node_count > 0 else 0.0

    # 孤立节点数
    isolated_count = sum(1 for n in graph.nodes() if graph.degree(n) == 0)

    stats = {
        "node_count": node_count,
        "edge_count": edge_count,
        "type_distribution": dict(type_dist),
        "relation_type_distribution": dict(rel_dist),
        "density": round(density, 6),
        "avg_degree": round(avg_degree, 4),
        "isolated_count": isolated_count,
        "input_entity_count": len(entities),
        "input_relation_count": len(relations),
    }

    logger.info(
        f"统计生成: {node_count} 节点, {edge_count} 边, "
        f"density={density:.4f}, avg_degree={avg_degree:.2f}, isolated={isolated_count}"
    )
    return stats


def generate_from_graph_only(graph) -> dict:
    """仅从图生成统计（无外部实体/关系列表）。

    Args:
        graph: nx.DiGraph

    Returns:
        统计字典
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    # 实体类型分布（从节点属性读取）
    type_dist: dict[str, int] = defaultdict(int)
    for _, data in graph.nodes(data=True):
        ntype = data.get("node_type", "unknown")
        type_dist[ntype] += 1

    # 关系类型分布（从边属性读取）
    rel_dist: dict[str, int] = defaultdict(int)
    for _, _, data in graph.edges(data=True):
        rtype = data.get("relation_type", "relates_to")
        rel_dist[rtype] += 1

    # 图密度
    if node_count > 1:
        density = 2 * edge_count / (node_count * (node_count - 1))
    else:
        density = 0.0

    avg_degree = 2 * edge_count / node_count if node_count > 0 else 0.0
    isolated_count = sum(1 for n in graph.nodes() if graph.degree(n) == 0)

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "type_distribution": dict(type_dist),
        "relation_type_distribution": dict(rel_dist),
        "density": round(density, 6),
        "avg_degree": round(avg_degree, 4),
        "isolated_count": isolated_count,
    }
