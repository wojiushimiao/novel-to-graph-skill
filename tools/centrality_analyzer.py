#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 中心性分析器

锚定: L2_数据模型与核心算法.md §2.12
      L3_接口契约与约束.md §1.4.1

计算三类中心性：度中心性、介数中心性、特征向量中心性。
"""

from __future__ import annotations

import logging

try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    nx = None
    _HAS_NETWORKX = False

from .models import (
    BETWEENNESS_SAMPLE_K,
    BETWEENNESS_SAMPLE_THRESHOLD,
    TOP_N_CENTRALITY,
)

logger = logging.getLogger(__name__)


def analyze(graph) -> dict[str, dict[str, float]]:
    """计算三类中心性。

    Args:
        graph: nx.DiGraph

    Returns:
        {
            "degree": {node_id: score},
            "betweenness": {node_id: score},
            "eigenvector": {node_id: score},
        }
    """
    if not _HAS_NETWORKX:
        raise RuntimeError("NetworkX 未安装")

    if graph.number_of_nodes() == 0:
        return {"degree": {}, "betweenness": {}, "eigenvector": {}}

    undirected = graph.to_undirected()
    n_nodes = undirected.number_of_nodes()

    # 度中心性
    degree_cent = nx.degree_centrality(undirected)

    # 介数中心性（节点数超阈值时抽样）
    if n_nodes > BETWEENNESS_SAMPLE_THRESHOLD:
        try:
            k = min(BETWEENNESS_SAMPLE_K, n_nodes)
            betweenness_cent = nx.betweenness_centrality(undirected, k=k)
            logger.info(f"介数中心性抽样: k={k}/{n_nodes}")
        except Exception as exc:
            logger.warning(f"介数中心性计算失败（降级为0）: {exc}")
            betweenness_cent = {n: 0.0 for n in undirected.nodes()}
    else:
        try:
            betweenness_cent = nx.betweenness_centrality(undirected)
        except Exception as exc:
            logger.warning(f"介数中心性计算失败（降级为0）: {exc}")
            betweenness_cent = {n: 0.0 for n in undirected.nodes()}

    # 特征向量中心性
    try:
        eigenvector_cent = nx.eigenvector_centrality_numpy(undirected)
    except Exception as exc:
        logger.warning(f"特征向量中心性计算失败（降级为0）: {exc}")
        try:
            eigenvector_cent = nx.eigenvector_centrality(undirected, max_iter=200, tol=1e-4)
        except Exception:
            eigenvector_cent = {n: 0.0 for n in undirected.nodes()}

    logger.info(
        f"中心性分析完成: {len(degree_cent)} 节点 "
        f"(最高度中心性: {max(degree_cent.values()) if degree_cent else 0:.4f})"
    )

    return {
        "degree": dict(degree_cent),
        "betweenness": dict(betweenness_cent),
        "eigenvector": dict(eigenvector_cent),
    }


def top_n(
    centrality: dict[str, float],
    n: int = TOP_N_CENTRALITY,
) -> list[dict]:
    """获取中心性 Top-N。

    Args:
        centrality: {node_id: score}
        n: Top-N 数量

    Returns:
        [{"id": node_id, "score": score}, ...] 按 score 降序
    """
    sorted_items = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
    return [{"id": nid, "score": score} for nid, score in sorted_items[:n]]


def top_n_all(
    analysis: dict[str, dict[str, float]],
    n: int = TOP_N_CENTRALITY,
) -> dict[str, list[dict]]:
    """获取三类中心性 Top-N。

    Args:
        analysis: analyze() 返回的结果
        n: Top-N 数量

    Returns:
        {"degree": [...], "betweenness": [...], "eigenvector": [...]}
    """
    return {
        "degree": top_n(analysis.get("degree", {}), n),
        "betweenness": top_n(analysis.get("betweenness", {}), n),
        "eigenvector": top_n(analysis.get("eigenvector", {}), n),
    }
