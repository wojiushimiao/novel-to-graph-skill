#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 社群检测器

锚定: L2_数据模型与核心算法.md §2.13
      L3_接口契约与约束.md §1.4.2

Louvain 社群检测（首选），降级为连通分量分析。
"""

from __future__ import annotations

import logging

try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    nx = None
    _HAS_NETWORKX = False

try:
    import community as community_louvain
    _HAS_LOUVAIN = True
except ImportError:
    community_louvain = None
    _HAS_LOUVAIN = False

logger = logging.getLogger(__name__)


def detect(graph) -> dict[int, list[str]]:
    """社群检测（Louvain 首选，降级连通分量）。

    Args:
        graph: nx.DiGraph

    Returns:
        {community_id: [node_id, ...]}
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    if graph.number_of_nodes() == 0:
        return {}

    undirected = graph.to_undirected()

    if _HAS_LOUVAIN:
        try:
            partition = community_louvain.best_partition(undirected)
            # partition: {node_id: community_id}
            communities: dict[int, list[str]] = {}
            for node, cid in partition.items():
                communities.setdefault(cid, []).append(node)
            logger.info(
                f"Louvain 社群检测完成: {len(communities)} 社群 "
                f"(最大社群 {max(len(v) for v in communities.values()) if communities else 0} 节点)"
            )
            # 重映射 ID 为 0-based 连续
            return {i: nodes for i, (_, nodes) in enumerate(sorted(communities.items(), key=lambda x: -len(x[1])))}
        except Exception as exc:
            logger.warning(f"Louvain 检测失败，降级为连通分量: {exc}")

    # 降级：连通分量
    return _detect_connected_components(undirected)


def _detect_connected_components(undirected) -> dict[int, list[str]]:
    """连通分量分析（降级方案）。"""
    components = list(nx.connected_components(undirected))
    # 按大小降序排序
    components.sort(key=len, reverse=True)
    communities = {i: list(comp) for i, comp in enumerate(components)}
    logger.info(
        f"连通分量分析完成: {len(communities)} 社群 "
        f"(最大社群 {len(components[0]) if components else 0} 节点)"
    )
    return communities


def detect_with_stats(graph) -> tuple[dict[int, list[str]], dict]:
    """社群检测并返回统计信息。

    Returns:
        (communities, stats)
        stats: {
            "method": "louvain"|"connected_components",
            "community_count": int,
            "largest_community_size": int,
            "average_community_size": float,
            "modularity": float | None,
        }
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    if graph.number_of_nodes() == 0:
        return {}, {"method": "none", "community_count": 0, "largest_community_size": 0,
                    "average_community_size": 0.0, "modularity": None}

    undirected = graph.to_undirected()
    method = "connected_components"
    modularity = None

    if _HAS_LOUVAIN:
        try:
            partition = community_louvain.best_partition(undirected)
            modularity = community_louvain.modularity(partition, undirected)
            method = "louvain"
            communities: dict[int, list[str]] = {}
            for node, cid in partition.items():
                communities.setdefault(cid, []).append(node)
            communities = {i: nodes for i, (_, nodes) in enumerate(sorted(communities.items(), key=lambda x: -len(x[1])))}
        except Exception as exc:
            logger.warning(f"Louvain 检测失败，降级: {exc}")
            communities = _detect_connected_components(undirected)
    else:
        communities = _detect_connected_components(undirected)

    sizes = [len(v) for v in communities.values()]
    stats = {
        "method": method,
        "community_count": len(communities),
        "largest_community_size": max(sizes) if sizes else 0,
        "average_community_size": sum(sizes) / len(sizes) if sizes else 0.0,
        "modularity": modularity,
    }
    logger.info(f"社群检测 ({method}): {stats}")
    return communities, stats
