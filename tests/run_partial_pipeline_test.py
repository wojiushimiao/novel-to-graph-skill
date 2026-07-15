#!/usr/bin/env python3
"""novel-analysis-skill · 部分数据S4-S7管线验证脚本

从已完成的 chunk_*.json 文件加载部分数据，执行 S4-S7 管线验证。
此脚本用于在全量LLM提取仍在进行时，验证下游管线的正确性。

输出:
- output_partial/partial_graph.db
- output_partial/partial_report.html
- output_partial/partial_report.md
- output_partial/partial_report.json
- output_partial/partial_metrics.json
"""
from __future__ import annotations

import sys
import os
import json
import time
import logging
import glob
from pathlib import Path
from collections import defaultdict

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
CHUNKS_DIR = WORKSPACE / 'llm_outputs'
OUTPUT_DIR = WORKSPACE / 'output_partial'
DB_PATH = OUTPUT_DIR / 'partial_graph.db'
HTML_PATH = OUTPUT_DIR / 'partial_report.html'
MD_PATH = OUTPUT_DIR / 'partial_report.md'
JSON_PATH = OUTPUT_DIR / 'partial_report.json'
METRICS_PATH = OUTPUT_DIR / 'partial_metrics.json'

sys.path.insert(0, str(SKILL_DIR))

from tools.models import Entity, Relation
from tools import (
    json_cleaner,
    schema_validator,
    low_value_filter,
    quantifier,
    id_router,
    entity_merger,
    db_writer,
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
logger = logging.getLogger('partial_pipeline')


def load_chunk_files() -> list[dict]:
    """加载所有已完成的 chunk_*.json 文件"""
    chunk_files = sorted(CHUNKS_DIR.glob('chunk_*.json'))
    logger.info(f'发现 {len(chunk_files)} 个 chunk 文件')

    all_items: list[dict] = []
    for cf in chunk_files:
        try:
            data = json.loads(cf.read_text(encoding='utf-8'))
            items = data.get('items', [])
            chapter = data.get('chapter', '')
            for item in items:
                item['_source_chapter'] = chapter
                item['_chunk_index'] = data.get('chunk_index', -1)
            all_items.extend(items)
        except Exception as exc:
            logger.warning(f'加载失败 {cf.name}: {exc}')

    logger.info(f'共加载 {len(all_items)} 条记录 (来自 {len(chunk_files)} 个chunks)')
    return all_items


def s4_clean_validate(items: list[dict]) -> list[dict]:
    """S4: 清洗校验"""
    print('\n=== S4: 清洗校验 ===')
    raw_dicts = [item for item in items if isinstance(item, dict)]
    print(f'[S4.1] json_cleaner: {len(items)} → {len(raw_dicts)} (过滤非字典)')

    validated = schema_validator.validate(raw_dicts)
    print(f'[S4.2] schema_validator: {len(raw_dicts)} → {len(validated)}')

    filtered = low_value_filter.filter(validated)
    print(f'[S4.3] low_value_filter: {len(validated)} → {len(filtered)}')

    return filtered


def convert_to_entities_relations(items: list[dict]) -> tuple[list[Entity], list[Relation]]:
    """将 LLM 输出字典转为 Entity/Relation 对象"""
    entities_map: dict[str, Entity] = {}
    relations: list[Relation] = []

    def get_or_create_entity(entity_id: str, name: str = '', entity_type: str = '') -> Entity:
        if entity_id in entities_map:
            return entities_map[entity_id]
        if not name:
            name = entity_id[2:] if len(entity_id) > 2 and entity_id[1] == '_' else entity_id
        if not entity_type:
            prefix = entity_id[0] if entity_id else 'X'
            type_map = {
                'C': 'character', 'L': 'location', 'E': 'event',
                'I': 'item', 'R': 'rule', 'S': 'system',
            }
            entity_type = type_map.get(prefix, 'event')
        e = Entity(
            id=entity_id,
            name=name,
            type=entity_type,
            base_info={'name': name},
            detail_info={},
            stitch_tags={},
            coords={},
        )
        entities_map[entity_id] = e
        return e

    for item in items:
        target_id = item.get('delta_update', {}).get('target_entity_id', '')
        if not target_id:
            continue

        source_chapter = item.get('_source_chapter', '')

        main_entity = get_or_create_entity(target_id)

        updated_fields = item.get('delta_update', {}).get('updated_fields', {})
        info = updated_fields.get('info', '')

        if info:
            existing_info = main_entity.detail_info.get('info', '')
            if existing_info:
                main_entity.detail_info['info'] = existing_info + '\n\n---\n\n' + info
            else:
                main_entity.detail_info['info'] = info

        stitch = item.get('stitch', {})
        if stitch:
            for k in ('sigma', 'epsilon', 'kappa'):
                v = stitch.get(k, '')
                if v:
                    existing = main_entity.stitch_tags.get(k, '')
                    if v not in existing:
                        main_entity.stitch_tags[k] = (existing + ' | ' + v).strip(' |') if existing else v

        coords = item.get('coords', {})
        if coords:
            for k in ('T', 'L', 'C', 'E', 'K'):
                v = coords.get(k, [])
                if isinstance(v, str):
                    v = [v]
                if v:
                    existing = main_entity.coords.get(k, [])
                    merged = list(set(existing + v))
                    main_entity.coords[k] = merged
            r = coords.get('R', {})
            if r and isinstance(r, dict) and r.get('subtype'):
                main_entity.coords['R'] = r

        importance = item.get('importance', 'low')
        main_entity.base_info.setdefault('importance_scores', []).append(importance)

        if source_chapter:
            if not main_entity.source_chapter:
                main_entity.source_chapter = source_chapter

        if item.get('delta_update', {}).get('conflict_detected', False):
            conflict_note = item.get('delta_update', {}).get('conflict_note', '')
            main_entity.base_info.setdefault('conflicts', []).append({
                'chapter': source_chapter,
                'note': conflict_note,
            })

        relations_data = updated_fields.get('new_wiki_relations', [])
        for rel_data in relations_data:
            target = rel_data.get('target', '')
            rel_type = rel_data.get('type', 'relates_to')
            strength = rel_data.get('strength', 'weak')

            if not target:
                continue

            if target.startswith(('C_', 'L_', 'E_', 'I_', 'R_', 'S_')):
                target_entity_id = target
            else:
                type_map = {
                    'located_in': 'L',
                    'participates_in': 'E',
                    'relates_to': 'C',
                    'evolves_to': 'C',
                    'causes': 'E',
                    'belongs_to': 'L',
                    'references': 'I',
                }
                prefix = type_map.get(rel_type, 'C')
                target_entity_id = f'{prefix}_{target}'

            get_or_create_entity(target_entity_id, name=target if not target.startswith(('C_', 'L_', 'E_', 'I_', 'R_', 'S_')) else '')

            relations.append(Relation(
                source_id=target_id,
                target_id=target_entity_id,
                relation_type=rel_type,
                strength=strength,
                description=info[:200] if info else '',
                source_chapter=source_chapter,
            ))

    entities = list(entities_map.values())
    logger.info(f'转换完成: {len(entities)} 实体, {len(relations)} 关系')
    return entities, relations


def s5_write_to_db(items: list[dict]) -> tuple[list[Entity], list[Relation]]:
    """S5: 规范化写入 DB"""
    print('\n=== S5: 规范化写入 DB ===')

    quantified = quantifier.map_importance(items)
    print(f'[S5.1] quantifier: {len(items)} → {len(quantified)}')

    entities, relations = convert_to_entities_relations(quantified)
    print(f'[S5.2] 转换: {len(entities)} 实体, {len(relations)} 关系')

    id_router.route(entities, conn=None)
    print(f'[S5.3] id_router: 完成')

    entities, relations = entity_merger.merge(entities, relations)
    print(f'[S5.4] entity_merger: {len(entities)} 实体, {len(relations)} 关系')

    # S5.4b: 过滤引用不存在实体的关系（entity_merger 合并后可能产生悬空引用）
    valid_ids = {e.id for e in entities}
    before_count = len(relations)
    relations = [r for r in relations if r.source_id in valid_ids and r.target_id in valid_ids]
    dropped = before_count - len(relations)
    if dropped > 0:
        print(f'[S5.4b] 关系过滤: {before_count} → {len(relations)} (丢弃 {dropped} 条悬空引用)')

    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = db_writer.write_all(str(DB_PATH), entities, relations)
    print(f'[S5.5] db_writer: {DB_PATH} ({DB_PATH.stat().st_size/1024/1024:.1f}MB)')
    conn.close()

    return entities, relations


def s7_generate_reports(entities: list[Entity], relations: list[Relation]):
    """S7: 触发报表"""
    print('\n=== S7: 触发报表 ===')

    graph = graph_builder.build(entities, relations)
    print(f'[S7.1] graph_builder: {graph.number_of_nodes()} 节点, {graph.number_of_edges()} 边')

    centrality = centrality_analyzer.analyze(graph)
    top_centrality = centrality_analyzer.top_n_all(centrality, n=20)
    print(f'[S7.2] centrality_analyzer: 完成')

    communities = community_detector.detect(graph)
    print(f'[S7.3] community_detector: {len(communities)} 社群')

    bridges = bridges_finder.find(graph, communities)
    print(f'[S7.4] bridges_finder: {len(bridges)} 桥接节点')

    orphans = orphans_finder.find(graph)
    print(f'[S7.5] orphans_finder: {len(orphans)} 孤儿节点')

    stats = stats_generator.generate(graph, entities, relations)
    print(f'[S7.6] stats_generator: density={stats["density"]}, avg_degree={stats["avg_degree"]}')

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

    html_path = html_renderer.render(
        graph=graph,
        analysis=analysis,
        stats=stats,
        title='全职法师 · 部分LLM抽取验证报表 (v0.3.0)',
        output_path=HTML_PATH,
    )
    print(f'[S7.7] html_renderer: {html_path} ({HTML_PATH.stat().st_size/1024:.1f}KB)')

    md_content = exporter.to_markdown(graph, entities, relations, stats, title='全职法师 · 部分LLM抽取验证')
    MD_PATH.write_text(md_content, encoding='utf-8')
    print(f'[S7.8] exporter.to_markdown: {MD_PATH} ({MD_PATH.stat().st_size/1024:.1f}KB)')

    json_data = exporter.to_json(graph, entities, relations, stats, analysis=analysis)
    JSON_PATH.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[S7.9] exporter.to_json: {JSON_PATH} ({JSON_PATH.stat().st_size/1024:.1f}KB)')

    return stats, analysis


def compute_quality_metrics(items: list[dict], entities: list[Entity],
                            relations: list[Relation], stats: dict) -> dict:
    """计算质量指标"""
    metrics = {
        'llm_output_count': len(items),
        'entity_count': len(entities),
        'relation_count': len(relations),
        'node_count': stats.get('node_count', 0),
        'edge_count': stats.get('edge_count', 0),
        'density': stats.get('density', 0),
        'avg_degree': stats.get('avg_degree', 0),
        'isolated_count': stats.get('isolated_count', 0),
    }

    info_lengths = []
    for item in items:
        info = item.get('delta_update', {}).get('updated_fields', {}).get('info', '')
        info_lengths.append(len(info))
    if info_lengths:
        metrics['info_avg_length'] = round(sum(info_lengths) / len(info_lengths), 2)
        metrics['info_min_length'] = min(info_lengths)
        metrics['info_max_length'] = max(info_lengths)
        metrics['info_qualified_count'] = sum(1 for l in info_lengths if 500 <= l <= 1500)
        metrics['info_qualified_rate'] = round(metrics['info_qualified_count'] / len(info_lengths), 4)

    importance_dist = {'high': 0, 'medium': 0, 'low': 0}
    for item in items:
        imp = item.get('importance', 'low')
        if imp in importance_dist:
            importance_dist[imp] += 1
    metrics['importance_distribution'] = importance_dist

    conflict_count = sum(1 for item in items if item.get('delta_update', {}).get('conflict_detected', False))
    metrics['conflict_count'] = conflict_count
    metrics['conflict_rate'] = round(conflict_count / len(items) if items else 0, 4)

    type_dist = defaultdict(int)
    for e in entities:
        type_dist[e.type] += 1
    metrics['entity_type_distribution'] = dict(type_dist)

    rel_dist = defaultdict(int)
    for r in relations:
        rel_dist[r.relation_type] += 1
    metrics['relation_type_distribution'] = dict(rel_dist)

    mofan_id = 'C_莫凡'
    if mofan_id in [e.id for e in entities]:
        mofan_degree = sum(1 for r in relations if r.source_id == mofan_id or r.target_id == mofan_id)
        metrics['mofan_degree'] = mofan_degree

    degree_counter = defaultdict(int)
    for r in relations:
        degree_counter[r.source_id] += 1
        degree_counter[r.target_id] += 1
    if degree_counter:
        metrics['max_degree'] = max(degree_counter.values())
        metrics['max_degree_entity'] = max(degree_counter, key=degree_counter.get)

    return metrics


def main():
    print('=== novel-analysis-skill · 部分数据 S4-S7 管线验证 ===\n')

    t0 = time.time()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    items = load_chunk_files()

    if not items:
        print('无数据可处理，退出')
        return

    filtered = s4_clean_validate(items)
    entities, relations = s5_write_to_db(filtered)
    stats, analysis = s7_generate_reports(entities, relations)

    print('\n=== 质量指标 ===')
    metrics = compute_quality_metrics(filtered, entities, relations, stats)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    METRICS_PATH.write_text(json.dumps({
        'metrics': metrics,
        'chunk_count': len(list(CHUNKS_DIR.glob('chunk_*.json'))),
        'elapsed_seconds': round(time.time() - t0, 2),
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n质量指标已保存: {METRICS_PATH}')

    elapsed = time.time() - t0
    print(f'\n=== 部分管线验证完成 (耗时 {elapsed:.1f}s) ===')


if __name__ == '__main__':
    main()
