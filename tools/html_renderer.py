#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · HTML 报表渲染器

锚定: L2_数据模型与核心算法.md §2.17
      L3_接口契约与约束.md §1.4.6 / §三·HTML报表接口契约

渲染 HTML 报表：序列化图数据为 JSON + 渲染 Jinja2 模板 + 内嵌交互 JS。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import (
    HTML_MAX_SIZE_MB,
    TOP_N_CENTRALITY,
    TOP_N_COMMUNITIES,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 模板文件路径（相对包根目录）
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html.j2"
_STATIC_JS_PATH = Path(__file__).resolve().parent.parent / "static" / "report.js"

# 社群颜色（最多20个社群）
_COMMUNITY_COLORS = [
    "#5B8FF9", "#5AD8A6", "#5D7092", "#F6BD16", "#E86452",
    "#6DC8EC", "#945FB9", "#FF9845", "#1E9493", "#FF99C3",
    "#286278", "#BCCUD9", "#54A0FF", "#48DBFB", "#1DD1A1",
    "#FECA57", "#FF6B6B", "#54A0FF", "#A29BFE", "#FD79A8",
]


def render(
    graph,
    analysis: dict,
    stats: dict,
    title: str = "",
    output_path: str | Path = "report.html",
    template_path: str | Path | None = None,
) -> Path:
    """渲染 HTML 报表。

    Args:
        graph: nx.DiGraph
        analysis: 中心性+社群+桥接+孤立实体分析结果
        stats: 统计报告
        title: 报表标题
        output_path: 输出文件路径
        template_path: Jinja2 模板路径，None 时用默认

    Returns:
        生成的 HTML 文件路径
    """
    # 序列化图数据为 JSON
    novel_data = _serialize_graph(graph, analysis, stats, title)

    # 检查体积
    data_size = len(json.dumps(novel_data, ensure_ascii=False))
    if data_size > HTML_MAX_SIZE_MB * 1024 * 1024:
        logger.warning(
            f"HTML 数据体积 {data_size/1024/1024:.1f}MB 超过阈值 {HTML_MAX_SIZE_MB}MB; "
            "已启用 Top-N 截断"
        )
        novel_data = _truncate_data(novel_data)

    # 渲染模板
    tpl_path = Path(template_path) if template_path else _TEMPLATE_PATH
    if not tpl_path.exists():
        logger.warning(f"模板不存在: {tpl_path}; 使用内置模板")
        html_content = _render_builtin(novel_data, title)
    else:
        env = Environment(
            loader=FileSystemLoader(str(tpl_path.parent)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        template = env.get_template(tpl_path.name)
        js_content = _read_static_js()
        html_content = template.render(
            title=title or "小说分析报表",
            generated_at=datetime.now().isoformat(),
            novel_data_json=json.dumps(novel_data, ensure_ascii=False, indent=2),
            static_js=js_content,
        )

    # 写入 HTML
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content, encoding="utf-8")
    logger.info(f"HTML 报表已生成: {out} ({out.stat().st_size/1024:.1f} KB)")
    return out


def _serialize_graph(
    graph,
    analysis: dict,
    stats: dict,
    title: str,
) -> dict:
    """序列化图数据为 window.NOVEL_DATA 结构。"""
    # 节点
    nodes = []
    for node_id, data in graph.nodes(data=True):
        nodes.append({
            "id": node_id,
            "label": data.get("label", node_id),
            "type": data.get("node_type", ""),
            "degree_centrality": analysis.get("degree", {}).get(node_id, 0.0),
            "betweenness_centrality": analysis.get("betweenness", {}).get(node_id, 0.0),
            "eigenvector_centrality": analysis.get("eigenvector", {}).get(node_id, 0.0),
            "community": _get_community(node_id, analysis.get("communities", {})),
            "base_info": data.get("base_info", {}),
            "coords": data.get("coords", {}),
            "source_chapter": data.get("source_chapter", ""),
        })

    # 边
    edges = []
    for i, (src, tgt, data) in enumerate(graph.edges(data=True)):
        edges.append({
            "id": f"r_{i:04d}",
            "source": src,
            "target": tgt,
            "source_label": graph.nodes[src].get("label", src) if src in graph else src,
            "target_label": graph.nodes[tgt].get("label", tgt) if tgt in graph else tgt,
            "relation_type": data.get("relation_type", "relates_to"),
            "strength": data.get("strength", "weak"),
            "weight": data.get("weight", 0.5),
            "description": data.get("description", ""),
        })

    # 社群
    communities_dict = {}
    raw_communities = analysis.get("communities", {})
    for cid, node_ids in raw_communities.items():
        color = _COMMUNITY_COLORS[cid % len(_COMMUNITY_COLORS)]
        communities_dict[str(cid)] = {
            "name": f"社群{cid + 1}",
            "node_ids": node_ids,
            "node_count": len(node_ids),
            "color": color,
        }

    # Top-N 中心性
    top_centralities = {
        "degree": _top_n_from_dict(analysis.get("degree", {})),
        "betweenness": _top_n_from_dict(analysis.get("betweenness", {})),
        "eigenvector": _top_n_from_dict(analysis.get("eigenvector", {})),
    }

    return {
        "title": title or "小说分析报表",
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "nodes": nodes,
        "edges": edges,
        "communities": communities_dict,
        "top_centralities": top_centralities,
        "bridges": analysis.get("bridges", []),
        "orphans": analysis.get("orphans", []),
    }


def _get_community(node_id: str, communities: dict) -> int:
    """查找节点所属社群。"""
    for cid, nodes in communities.items():
        if node_id in nodes:
            return cid
    return -1


def _top_n_from_dict(c: dict, n: int = TOP_N_CENTRALITY) -> list:
    """从字典获取 Top-N。"""
    sorted_items = sorted(c.items(), key=lambda x: x[1], reverse=True)
    return [{"id": nid, "score": round(score, 4)} for nid, score in sorted_items[:n]]


def _truncate_data(data: dict) -> dict:
    """Top-N 截断。"""
    data["nodes"] = data["nodes"][:TOP_N_CENTRALITY]
    data["edges"] = data["edges"][:TOP_N_CENTRALITY * 2]
    communities = data.get("communities", {})
    data["communities"] = dict(list(communities.items())[:TOP_N_COMMUNITIES])
    return data


def _read_static_js() -> str:
    """读取 static/report.js 内容。"""
    if _STATIC_JS_PATH.exists():
        return _STATIC_JS_PATH.read_text(encoding="utf-8")
    return "// report.js not found"


def _render_builtin(data: dict, title: str) -> str:
    """内置极简 HTML 模板（无 Jinja2 模板时使用）。"""
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    js_content = _read_static_js()
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title or "小说分析报表"}</title>
</head>
<body>
<div id="app"></div>
<script>window.NOVEL_DATA = {data_json};</script>
<script>{js_content}</script>
</body>
</html>"""
