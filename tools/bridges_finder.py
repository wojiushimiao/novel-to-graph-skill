#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 桥接节点识别器

锚定: L2_数据模型与核心算法.md §2.14
      L3_接口契约与约束.md §1.4.3

桥接节点 = 连接多个社群的节点。
bridge_score(v) = cross_community_edges(v) / total_edges(v)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    nx = None
    _HAS_NETWORKX = False

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def find(
    graph,
    communities: dict[int, list[str]],
    min_cross_edges: int = 2,
) -> list[dict]:
    """识别桥接节点。

    Args:
        graph: nx.DiGraph
        communities: {community_id: [node_ids]}
        min_cross_edges: 最小跨社群边数阈值

    Returns:
        [{"node_id": str, "label": str, "bridge_score": float,
           "cross_edges": [{"target": str, "community": int}], "cross_community_count": int}]
        按 bridge_score 降序
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    if graph.number_of_nodes() == 0:
        return []

    # 构建 node_id → community_id 索引
    node_to_comm: dict[str, int] = {}
    for cid, nodes in communities.items():
        for node in nodes:
            node_to_comm[node] = cid

    bridges: list[dict] = []

    for node in graph.nodes():
        # 该节点的社群
        my_comm = node_to_comm.get(node)
        if my_comm is None:
            continue

        # 计算跨社群边数
        cross_edges: list[dict] = []
        total_edges = 0

        for _, target in graph.out_edges(node):
            total_edges += 1
            target_comm = node_to_comm.get(target)
            if target_comm is not None and target_comm != my_comm:
                cross_edges.append({"target": target, "community": target_comm})

        for source, _ in graph.in_edges(node):
            total_edges += 1
            source_comm = node_to_comm.get(source)
            if source_comm is not None and source_comm != my_comm:
                cross_edges.append({"target": source, "community": source_comm})

        if len(cross_edges) < min_cross_edges:
            continue

        bridge_score = len(cross_edges) / total_edges if total_edges > 0 else 0.0
        cross_communities = {ce["community"] for ce in cross_edges}

        bridges.append({
            "node_id": node,
            "label": graph.nodes[node].get("label", node),
            "node_type": graph.nodes[node].get("node_type", ""),
            "bridge_score": round(bridge_score, 4),
            "cross_edges": cross_edges,
            "cross_community_count": len(cross_communities),
            "total_edges": total_edges,
        })

    bridges.sort(key=lambda x: x["bridge_score"], reverse=True)
    logger.info(f"桥接节点识别: {len(bridges)} 个 (阈值={min_cross_edges})")
    return bridges
