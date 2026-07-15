#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 孤立实体检测器

锚定: L2_数据模型与核心算法.md §2.15
      L3_接口契约与约束.md §1.4.4

检测度为0的节点（无任何关系连接）。
"""

from __future__ import annotations

import logging

try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    nx = None
    _HAS_NETWORKX = False

logger = logging.getLogger(__name__)


def find(graph) -> list[str]:
    """检测孤立实体（度为0的节点）。

    Args:
        graph: nx.DiGraph

    Returns:
        [node_id, ...]
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    if graph.number_of_nodes() == 0:
        return []

    orphans = [n for n in graph.nodes() if graph.degree(n) == 0]
    logger.info(f"孤立实体检测: {len(orphans)} 个 (总节点 {graph.number_of_nodes()})")
    return orphans


def find_with_details(graph) -> list[dict]:
    """检测孤立实体并返回详细信息。

    Args:
        graph: nx.DiGraph

    Returns:
        [{"id": str, "label": str, "type": str}]
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    if graph.number_of_nodes() == 0:
        return []

    result = []
    for node in graph.nodes():
        if graph.degree(node) == 0:
            result.append({
                "id": node,
                "label": graph.nodes[node].get("label", node),
                "type": graph.nodes[node].get("node_type", ""),
            })

    logger.info(f"孤立实体检测(详细): {len(result)} 个")
    return result
