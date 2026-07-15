#!/usr/bin/env python3
"""novel-to-graph-skill · 最终报表生成脚本

基于 S6 审查后的 DB (full_llm_graph_s6.db) 生成：
- 最终 HTML 关系图谱（含 Cytoscape.js 力导向图）
- 最终 Markdown 世界设定集
- 最终 JSON 导出
- 质量指标对比报告

输出:
- output/final_report.html — 最终 HTML 报表
- output/final_report.md — 最终 Markdown 世界设定集
- output/final_report.json — 最终 JSON 导出
- output/final_metrics.json — 最终质量指标
"""
from __future__ import annotations

import sys
import os
import json
import time
import sqlite3
import logging
from pathlib import Path
from collections import defaultdict

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-to-graph-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
OUTPUT_DIR = WORKSPACE / 'output'
S6_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s6.db'
HTML_PATH = OUTPUT_DIR / 'final_report.html'
MD_PATH = OUTPUT_DIR / 'final_report.md'
JSON_PATH = OUTPUT_DIR / 'final_report.json'
METRICS_PATH = OUTPUT_DIR / 'final_metrics.json'

sys.path.insert(0, str(SKILL_DIR))

from tools.models import Entity, Relation
from tools import (
    graph_builder,
    centrality_analyzer,
    community_detector,
    bridges_finder,
    orphans_finder,
    stats_generator,
    html_renderer,
    exporter,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('final_report')


def load_from_s6_db(db_path: Path) -> tuple[list[Entity], list[Relation]]:
    """从 S6 审查后的 DB 加载实体和关系"""
    logger.info(f'从 S6 DB 加载: {db_path}')
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    entities = []
    for row in conn.execute('SELECT * FROM entities'):
        base_info = row['base_info']
        detail_info = row['detail_info']
        stitch_tags = row['stitch_tags']
        coords = row['coords']
        try:
            base_info = json.loads(base_info) if base_info else {}
        except (json.JSONDecodeError, TypeError):
            base_info = {}
        try:
            detail_info = json.loads(detail_info) if detail_info else {}
        except (json.JSONDecodeError, TypeError):
            detail_info = {}
        try:
            stitch_tags = json.loads(stitch_tags) if stitch_tags else {}
        except (json.JSONDecodeError, TypeError):
            stitch_tags = {}
        try:
            coords = json.loads(coords) if coords else {}
        except (json.JSONDecodeError, TypeError):
            coords = {}

        e = Entity(
            id=row['id'],
            name=row['name'],
            type=row['type'],
            base_info=base_info,
            detail_info=detail_info,
            stitch_tags=stitch_tags,
            coords=coords,
            source_chapter=row['source_chapter'] or '',
            char_offset=row['char_offset'] or 0,
        )
        entities.append(e)

    relations = []
    for row in conn.execute('SELECT * FROM wiki_relations'):
        r = Relation(
            source_id=row['source_id'],
            target_id=row['target_id'],
            relation_type=row['relation_type'],
            strength=row['strength'] or 'weak',
            description=row['description'] or '',
            source_chapter=row['source_chapter'] or '',
        )
        relations.append(r)

    conn.close()
    logger.info(f'加载: {len(entities)} 实体, {len(relations)} 关系')
    return entities, relations


def filter_important_entities(entities: list[Entity], relations: list[Relation],
                              max_count: int = 2000) -> tuple[list[Entity], list[Relation]]:
    """过滤出最重要的实体（避免报表过大）

    策略：
    1. 保留所有 importance=high 的实体
    2. 保留所有有关系的实体（非孤儿）
    3. 限制总数在 max_count 内
    """
    # 计算度数
    degree = defaultdict(int)
    for r in relations:
        degree[r.source_id] += 1
        degree[r.target_id] += 1

    # 按重要度排序
    def importance_score(e: Entity) -> float:
        base_info = e.base_info if isinstance(e.base_info, dict) else {}
        scores = base_info.get('importance_scores', []) if isinstance(base_info, dict) else []
        if 'high' in scores:
            return 1.0
        elif 'medium' in scores:
            return 0.5
        return 0.15

    # 过滤：有关系的 + 高重要度
    candidates = []
    for e in entities:
        deg = degree[e.id]
        imp = importance_score(e)
        if deg > 0 or imp >= 0.85:
            candidates.append((e, deg, imp))

    # 排序：度数 * 重要度
    candidates.sort(key=lambda x: (x[1] * x[2], x[1]), reverse=True)

    # 截断
    if len(candidates) > max_count:
        candidates = candidates[:max_count]

    selected_ids = {c[0].id for c in candidates}
    filtered_entities = [c[0] for c in candidates]
    filtered_relations = [r for r in relations
                          if r.source_id in selected_ids and r.target_id in selected_ids]

    logger.info(f'过滤: {len(entities)} → {len(filtered_entities)} 实体, '
                f'{len(relations)} → {len(filtered_relations)} 关系')
    return filtered_entities, filtered_relations


def generate_reports(entities: list[Entity], relations: list[Relation]):
    """生成完整报表"""
    print('\n=== 生成最终报表 ===')

    # S7.1: graph_builder
    graph = graph_builder.build(entities, relations)
    print(f'[1] graph_builder: {graph.number_of_nodes()} 节点, {graph.number_of_edges()} 边')

    # S7.2: centrality_analyzer
    centrality = centrality_analyzer.analyze(graph)
    top_centrality = centrality_analyzer.top_n_all(centrality, n=20)
    print(f'[2] centrality_analyzer: 完成')

    # S7.3: community_detector
    communities = community_detector.detect(graph)
    print(f'[3] community_detector: {len(communities)} 社群')

    # S7.4: bridges_finder
    bridges = bridges_finder.find(graph, communities)
    print(f'[4] bridges_finder: {len(bridges)} 桥接节点')

    # S7.5: orphans_finder
    orphans = orphans_finder.find(graph)
    print(f'[5] orphans_finder: {len(orphans)} 孤儿节点')

    # S7.6: stats_generator
    stats = stats_generator.generate(graph, entities, relations)
    print(f'[6] stats_generator: density={stats["density"]}, avg_degree={stats["avg_degree"]}')

    # 组装 analysis
    analysis = {
        'degree': centrality.get('degree', {}),
        'betweenness': centrality.get('betweenness', {}),
        'eigenvector': centrality.get('eigenvector', {}),
        'communities': communities,
        'bridges': bridges,
        'orphans': orphans,
        'top_centrality': top_centrality,
        'degree_centrality': centrality.get('degree', {}),
        'betweenness_centrality': centrality.get('betweenness', {}),
        'eigenvector_centrality': centrality.get('eigenvector', {}),
    }

    # S7.7: html_renderer
    html_path = html_renderer.render(
        graph=graph,
        analysis=analysis,
        stats=stats,
        title='全职法师 · 完整世界设定集与关系图谱 (v0.3.0 · S6 轴化审查后)',
        output_path=HTML_PATH,
    )
    print(f'[7] html_renderer: {html_path} ({HTML_PATH.stat().st_size/1024/1024:.1f}MB)')

    # S7.8: exporter.to_markdown
    md_content = exporter.to_markdown(
        graph, entities, relations, stats,
        title='全职法师 · 完整世界设定集 (v0.3.0 · S6 轴化审查后)'
    )
    MD_PATH.write_text(md_content, encoding='utf-8')
    print(f'[8] exporter.to_markdown: {MD_PATH} ({MD_PATH.stat().st_size/1024:.1f}KB)')

    # S7.9: exporter.to_json
    json_data = exporter.to_json(graph, entities, relations, stats, analysis=analysis)
    JSON_PATH.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[9] exporter.to_json: {JSON_PATH} ({JSON_PATH.stat().st_size/1024/1024:.1f}MB)')

    return stats, analysis


def compute_final_metrics(entities: list[Entity], relations: list[Relation],
                          stats: dict, analysis: dict) -> dict:
    """计算最终质量指标"""
    metrics = {
        'entity_count': len(entities),
        'relation_count': len(relations),
        'node_count': stats.get('node_count', 0),
        'edge_count': stats.get('edge_count', 0),
        'density': stats.get('density', 0),
        'avg_degree': stats.get('avg_degree', 0),
        'isolated_count': stats.get('isolated_count', 0),
        'community_count': len(analysis.get('communities', {})),
        'bridge_count': len(analysis.get('bridges', [])),
        'orphan_count': len(analysis.get('orphans', [])),
    }

    # 实体类型分布
    type_dist = defaultdict(int)
    for e in entities:
        type_dist[e.type] += 1
    metrics['entity_type_distribution'] = dict(type_dist)

    # 关系类型分布（轴关系模型）
    rel_dist = defaultdict(int)
    for r in relations:
        rel_dist[r.relation_type] += 1
    metrics['relation_type_distribution'] = dict(rel_dist)

    # info 长度统计
    info_lengths = []
    for e in entities:
        info = e.detail_info.get('info', '') if isinstance(e.detail_info, dict) else ''
        if info:
            info_lengths.append(len(info))
    if info_lengths:
        metrics['info_avg_length'] = sum(info_lengths) / len(info_lengths)
        metrics['info_min_length'] = min(info_lengths)
        metrics['info_max_length'] = max(info_lengths)
        metrics['info_qualified_count'] = sum(1 for l in info_lengths if 500 <= l <= 1500)
        metrics['info_qualified_rate'] = metrics['info_qualified_count'] / len(info_lengths)

    # importance 分布
    importance_dist = {'high': 0, 'medium': 0, 'low': 0}
    for e in entities:
        base_info = e.base_info if isinstance(e.base_info, dict) else {}
        scores = base_info.get('importance_scores', []) if isinstance(base_info, dict) else []
        if 'high' in scores:
            importance_dist['high'] += 1
        elif 'medium' in scores:
            importance_dist['medium'] += 1
        else:
            importance_dist['low'] += 1
    metrics['importance_distribution'] = importance_dist

    # 冲突检测
    conflict_count = 0
    for e in entities:
        base_info = e.base_info if isinstance(e.base_info, dict) else {}
        conflicts = base_info.get('conflicts', []) if isinstance(base_info, dict) else []
        conflict_count += len(conflicts)
    metrics['conflict_count'] = conflict_count

    # 出度/入度统计
    out_degree = defaultdict(int)
    in_degree = defaultdict(int)
    for r in relations:
        out_degree[r.source_id] += 1
        in_degree[r.target_id] += 1

    if out_degree:
        metrics['max_out_degree'] = max(out_degree.values())
        metrics['max_out_entity'] = max(out_degree, key=out_degree.get)
    if in_degree:
        metrics['max_in_degree'] = max(in_degree.values())
        metrics['max_in_entity'] = max(in_degree, key=in_degree.get)

    # 莫凡度数
    mofan_id = 'C_莫凡'
    if mofan_id in {e.id for e in entities}:
        mofan_out = out_degree.get(mofan_id, 0)
        mofan_in = in_degree.get(mofan_id, 0)
        metrics['mofan_out_degree'] = mofan_out
        metrics['mofan_in_degree'] = mofan_in
        metrics['mofan_total_degree'] = mofan_out + mofan_in

    # Top 10 中心性实体
    degree_cent = analysis.get('degree', {})
    if degree_cent:
        top10 = sorted(degree_cent.items(), key=lambda x: x[1], reverse=True)[:10]
        metrics['top10_degree_centrality'] = [
            {'id': eid, 'name': next((e.name for e in entities if e.id == eid), eid), 'degree': deg}
            for eid, deg in top10
        ]

    return metrics


def main():
    print('=== novel-to-graph-skill · 最终报表生成 ===\n')

    t0 = time.time()

    if not S6_DB_PATH.exists():
        print(f'错误: S6 DB 不存在: {S6_DB_PATH}')
        print('请先运行 run_s6_llm_review.py 生成 S6 DB')
        sys.exit(1)

    # 从 S6 DB 加载
    entities, relations = load_from_s6_db(S6_DB_PATH)

    # 过滤出最重要的实体（避免报表过大）
    print(f'\n=== 过滤重要实体 ===')
    print(f'原始: {len(entities)} 实体, {len(relations)} 关系')
    entities, relations = filter_important_entities(entities, relations, max_count=2000)

    # 生成报表
    stats, analysis = generate_reports(entities, relations)

    # 计算最终质量指标
    print('\n=== 计算最终质量指标 ===')
    metrics = compute_final_metrics(entities, relations, stats, analysis)
    print(json.dumps(metrics, ensure_ascii=False, indent=2, default=str))

    # 保存指标
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
                            encoding='utf-8')
    print(f'\n质量指标已保存: {METRICS_PATH}')

    elapsed = time.time() - t0
    print(f'\n=== 完成 (耗时 {elapsed:.1f}s) ===')


if __name__ == '__main__':
    main()
