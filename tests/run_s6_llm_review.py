#!/usr/bin/env python3
"""novel-analysis-skill · S6 轴化图遍历审查脚本

按轴关系模型执行图遍历审查：
1. 旧关系轴化转换（7种旧关系 → 6种轴关系）
2. T_main 主轴构建（importance=high 事件按时序串联）
3. T_branch 鱼骨分支组织
4. 出边裁剪（扇出上限：角色≤5, 事件≤3, 其他=0）
5. 零散节点聚类
6. 幽灵节点合并

输出:
- output/full_llm_graph_s6.db — S6 审查后的 DB
- output/s6_review_report.json — 审查报告
"""
from __future__ import annotations

import sys
import os
import json
import time
import logging
import sqlite3
from pathlib import Path
from collections import defaultdict
from typing import Any

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
OUTPUT_DIR = WORKSPACE / 'output'
DB_PATH = OUTPUT_DIR / 'full_llm_graph.db'
S6_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s6.db'
S6_REPORT = OUTPUT_DIR / 's6_review_report.json'

sys.path.insert(0, str(SKILL_DIR))

from tools.models import Entity, Relation, LEGACY_TO_AXIS_MAP, ENTITY_OUT_EDGE_LIMITS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('s6_review')


def load_from_db(db_path: Path) -> tuple[list[dict], list[dict]]:
    """从 DB 加载实体和关系"""
    logger.info(f'从 DB 加载: {db_path}')
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    entities = []
    for row in conn.execute('SELECT * FROM entities'):
        e = dict(row)
        for k in ('base_info', 'detail_info', 'stitch_tags', 'coords'):
            if e.get(k):
                try:
                    e[k] = json.loads(e[k])
                except (json.JSONDecodeError, TypeError):
                    e[k] = {}
        entities.append(e)

    relations = []
    for row in conn.execute('SELECT * FROM wiki_relations'):
        relations.append(dict(row))

    conn.close()
    logger.info(f'加载: {len(entities)} 实体, {len(relations)} 关系')
    return entities, relations


def s6_1_axis_conversion(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """S6.1 旧关系轴化转换

    将旧7种关系类型映射为6种轴关系类型。
    """
    print('[S6.1] 旧关系轴化转换...')

    converted = 0
    for r in relations:
        old_type = r['relation_type']
        if old_type in LEGACY_TO_AXIS_MAP:
            r['relation_type'] = LEGACY_TO_AXIS_MAP[old_type]
            converted += 1

    print(f'  转换: {converted}/{len(relations)} 条关系')

    # 关系去重（转换后可能产生重复）
    seen = set()
    unique_relations = []
    dedup_count = 0
    for r in relations:
        key = (r['source_id'], r['target_id'], r['relation_type'])
        if key not in seen:
            seen.add(key)
            unique_relations.append(r)
        else:
            # 保留 strong 优先
            for existing in unique_relations:
                if (existing['source_id'] == r['source_id'] and
                    existing['target_id'] == r['target_id'] and
                    existing['relation_type'] == r['relation_type']):
                    if r.get('strength') == 'strong' and existing.get('strength') != 'strong':
                        existing['strength'] = 'strong'
                    break
            dedup_count += 1

    if dedup_count > 0:
        print(f'  转换后去重: {dedup_count} 条')
        relations = unique_relations

    stats = {
        'converted': converted,
        'deduped': dedup_count,
        'after_count': len(relations),
    }
    return entities, relations, stats


def s6_2_build_main_axis(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """S6.2 T_main 主轴构建

    从 importance=high 的事件中识别核心主线事件，按时序构建主轴链。
    """
    print('[S6.2] T_main 主轴构建...')

    # 找出 importance=high 的事件实体
    high_events = []
    for e in entities:
        if e['type'] == 'event':
            base_info = e.get('base_info', {})
            if isinstance(base_info, str):
                try:
                    base_info = json.loads(base_info)
                except:
                    base_info = {}
            importance_scores = base_info.get('importance_scores', []) if isinstance(base_info, dict) else []
            if not importance_scores:
                # 从 base_info.importance_score 获取
                imp_score = base_info.get('importance_score', 0) if isinstance(base_info, dict) else 0
                if imp_score >= 0.85:
                    high_events.append(e)
            elif 'high' in importance_scores:
                high_events.append(e)

    print(f'  importance=high 事件: {len(high_events)}')

    # 按 source_chapter 排序
    high_events.sort(key=lambda e: e.get('source_chapter', ''))

    # 构建 T_main 主轴链
    main_axis_count = 0
    for i in range(len(high_events) - 1):
        source_id = high_events[i]['id']
        target_id = high_events[i + 1]['id']

        # 检查是否已存在 T_main 关系
        exists = any(r for r in relations
                     if r['source_id'] == source_id
                     and r['target_id'] == target_id
                     and r['relation_type'] == 'T_main')
        if not exists:
            relations.append({
                'source_id': source_id,
                'target_id': target_id,
                'relation_type': 'T_main',
                'strength': 'strong',
                'description': '时序主轴串联',
                'source_chapter': high_events[i].get('source_chapter', ''),
            })
            main_axis_count += 1

    print(f'  新增 T_main 关系: {main_axis_count} 条')

    stats = {
        'high_events': len(high_events),
        't_main_added': main_axis_count,
    }
    return entities, relations, stats


def s6_4_out_edge_pruning(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """S6.4 出边裁剪（扇出上限）

    按轴模型扇出上限裁剪：
    - 角色 ≤ 5（仅 R_strong / A_arc）
    - 事件 ≤ 3（仅 T_main / A_causal）
    - 地点/物品/规则/系统 = 0
    """
    print('[S6.4] 出边裁剪（轴模型扇出限制）...')

    entity_types = {e['id']: e['type'] for e in entities}

    # 允许的扇出关系类型
    allowed_out_types = {
        'character': {'R_strong', 'A_arc'},
        'event': {'T_main', 'A_causal'},
        'location': set(),
        'item': set(),
        'rule': set(),
        'system': set(),
        'monster': set(),
        'knowledge': set(),
    }

    # 计算每个实体的出边
    out_edges = defaultdict(list)
    for r in relations:
        out_edges[r['source_id']].append(r)

    # 裁剪超限出边
    pruned_relations = set()  # 用 id(r) 标识
    prune_details = {}

    for eid, edges in out_edges.items():
        etype = entity_types.get(eid, 'event')
        limit = ENTITY_OUT_EDGE_LIMITS.get(etype, 0)
        allowed = allowed_out_types.get(etype, set())

        # 过滤不允许的出边类型
        disallowed = [r for r in edges if r['relation_type'] not in allowed]
        for r in disallowed:
            pruned_relations.add(id(r))

        # 允许的出边
        allowed_edges = [r for r in edges if r['relation_type'] in allowed]

        if len(allowed_edges) > limit:
            # 按 strength 排序，strong 优先
            allowed_edges.sort(key=lambda r: 0 if r.get('strength') == 'strong' else 1)
            kept = allowed_edges[:limit]
            kept_ids = {id(r) for r in kept}
            for r in allowed_edges:
                if id(r) not in kept_ids:
                    pruned_relations.add(id(r))
            prune_details[eid] = {
                'type': etype,
                'before': len(allowed_edges),
                'after': len(kept),
                'pruned': len(allowed_edges) - len(kept),
            }

    # 过滤被裁剪的关系
    final_relations = [r for r in relations if id(r) not in pruned_relations]

    pruned_count = len(relations) - len(final_relations)
    print(f'  裁剪: {len(relations)} → {len(final_relations)} (去除 {pruned_count} 条)')
    if prune_details:
        top5 = sorted(prune_details.items(), key=lambda x: -x[1]['before'])[:5]
        for eid, info in top5:
            print(f'    {eid} ({info["type"]}): {info["before"]} → {info["after"]}')

    stats = {
        'relations_before': len(relations),
        'relations_after': len(final_relations),
        'pruned_count': pruned_count,
        'pruned_entities': len(prune_details),
        'prune_details': {k: v for k, v in list(prune_details.items())[:20]},
    }
    return entities, final_relations, stats


def s6_5_orphan_clustering(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """S6.5 零散节点聚类

    对孤儿节点和微型节点进行聚类合并。
    """
    print('[S6.5] 零散节点聚类...')

    # 计算度数
    degree = defaultdict(int)
    for r in relations:
        degree[r['source_id']] += 1
        degree[r['target_id']] += 1

    orphan_ids = [eid for eid in [e['id'] for e in entities] if degree[eid] == 0]
    micro_ids = [eid for eid in [e['id'] for e in entities] if 0 < degree[eid] <= 1]

    print(f'  孤儿节点: {len(orphan_ids)}')
    print(f'  微型节点 (degree<=1): {len(micro_ids)}')

    # 同类型同名称合并
    name_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in entities:
        name_groups[(e['type'], e['name'])].append(e['id'])

    merge_map: dict[str, str] = {}
    merged_count = 0
    for (etype, name), ids in name_groups.items():
        if len(ids) > 1:
            keep_id = ids[0]
            for other_id in ids[1:]:
                merge_map[other_id] = keep_id
                merged_count += 1

    print(f'  同名同类型合并: {merged_count} 个实体')

    if merge_map:
        entities = [e for e in entities if e['id'] not in merge_map]
        for r in relations:
            r['source_id'] = merge_map.get(r['source_id'], r['source_id'])
            r['target_id'] = merge_map.get(r['target_id'], r['target_id'])
        # 去重
        seen = set()
        unique_relations = []
        for r in relations:
            key = (r['source_id'], r['target_id'], r['relation_type'])
            if key not in seen:
                seen.add(key)
                unique_relations.append(r)
        dedup_count = len(relations) - len(unique_relations)
        relations = unique_relations
        if dedup_count > 0:
            print(f'  合并后关系去重: {dedup_count} 条')

    stats = {
        'orphan_count': len(orphan_ids),
        'micro_count': len(micro_ids),
        'merged_by_name': merged_count,
    }
    return entities, relations, stats


def s6_3_ghost_node_merge(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """S6.3 幽灵节点合并

    检测主观修饰词命名的孤立节点。
    """
    print('[S6.3] 幽灵节点合并...')

    subjective_words = ['震撼', '悲惨', '惊天', '惊心动魄', '紧急', '意外', '清晨', '深夜',
                        '最终', '最后', '第一次', '突然', '猛烈', '激烈', '可怕', '惊人']

    ghost_candidates = []
    for e in entities:
        if e['type'] == 'event':
            for word in subjective_words:
                if word in e['name']:
                    ghost_candidates.append((e, word))
                    break

    print(f'  幽灵节点候选: {len(ghost_candidates)}')

    stats = {
        'ghost_candidates': len(ghost_candidates),
        'ghost_examples': [{'id': e['id'], 'name': e['name'], 'word': w} for e, w in ghost_candidates[:10]],
    }
    return entities, relations, stats


def s6_review(db_path: Path) -> dict:
    """S6 完整轴化审查流程"""
    print('\n=== S6: 轴化图遍历审查 ===\n')

    t0 = time.time()

    entities, relations = load_from_db(db_path)
    all_stats = {'initial': {'entities': len(entities), 'relations': len(relations)}}

    # S6.1 旧关系轴化转换
    entities, relations, stats_61 = s6_1_axis_conversion(entities, relations)
    all_stats['s6_1_axis_conversion'] = stats_61

    # S6.2 T_main 主轴构建
    entities, relations, stats_62 = s6_2_build_main_axis(entities, relations)
    all_stats['s6_2_main_axis'] = stats_62

    # S6.3 幽灵节点合并
    entities, relations, stats_63 = s6_3_ghost_node_merge(entities, relations)
    all_stats['s6_3_ghost_node'] = stats_63

    # S6.4 出边裁剪
    entities, relations, stats_64 = s6_4_out_edge_pruning(entities, relations)
    all_stats['s6_4_out_edge_pruning'] = stats_64

    # S6.5 零散节点聚类
    entities, relations, stats_65 = s6_5_orphan_clustering(entities, relations)
    all_stats['s6_5_orphan_cluster'] = stats_65

    all_stats['final'] = {'entities': len(entities), 'relations': len(relations)}

    # 关系类型分布统计
    rel_type_dist = defaultdict(int)
    for r in relations:
        rel_type_dist[r['relation_type']] += 1
    all_stats['final']['relation_type_distribution'] = dict(rel_type_dist)

    # 出边/入边统计
    out_degree = defaultdict(int)
    in_degree = defaultdict(int)
    for r in relations:
        out_degree[r['source_id']] += 1
        in_degree[r['target_id']] += 1

    max_out = max(out_degree.values()) if out_degree else 0
    max_in = max(in_degree.values()) if in_degree else 0
    all_stats['final']['max_out_degree'] = max_out
    all_stats['final']['max_in_degree'] = max_in
    all_stats['final']['max_out_entity'] = max(out_degree, key=out_degree.get) if out_degree else ''
    all_stats['final']['max_in_entity'] = max(in_degree, key=in_degree.get) if in_degree else ''

    # 写入 S6 后的 DB
    print(f'\n[S6] 写入审查后的 DB: {S6_DB_PATH}')
    from tools import db_writer

    ent_objs = []
    for e in entities:
        ent_objs.append(Entity(
            id=e['id'],
            name=e['name'],
            type=e['type'],
            base_info=e.get('base_info', {}) if isinstance(e.get('base_info'), dict) else {},
            detail_info=e.get('detail_info', {}) if isinstance(e.get('detail_info'), dict) else {},
            stitch_tags=e.get('stitch_tags', {}) if isinstance(e.get('stitch_tags'), dict) else {},
            coords=e.get('coords', {}) if isinstance(e.get('coords'), dict) else {},
            source_chapter=e.get('source_chapter', ''),
        ))

    rel_objs = []
    for r in relations:
        rel_objs.append(Relation(
            source_id=r['source_id'],
            target_id=r['target_id'],
            relation_type=r['relation_type'],
            strength=r.get('strength', 'weak'),
            description=r.get('description', ''),
            source_chapter=r.get('source_chapter', ''),
        ))

    if S6_DB_PATH.exists():
        S6_DB_PATH.unlink()
    conn = db_writer.write_all(str(S6_DB_PATH), ent_objs, rel_objs)
    conn.close()
    print(f'[S6] DB 写入完成: {S6_DB_PATH} ({S6_DB_PATH.stat().st_size/1024/1024:.1f}MB)')

    all_stats['elapsed_seconds'] = time.time() - t0
    all_stats['s6_db_path'] = str(S6_DB_PATH)

    S6_REPORT.write_text(json.dumps(all_stats, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(f'[S6] 审查报告: {S6_REPORT}')

    return all_stats


def main():
    print('=== novel-analysis-skill · S6 轴化图遍历审查 ===\n')

    if not DB_PATH.exists():
        print(f'错误: DB 不存在: {DB_PATH}')
        print('请先运行 run_s4_s7_pipeline.py 生成 DB')
        sys.exit(1)

    stats = s6_review(DB_PATH)

    print('\n=== S6 审查完成 ===')
    print(json.dumps({k: v for k, v in stats.items() if k not in ('s6_1_axis_conversion', 's6_2_main_axis', 's6_3_ghost_node', 's6_4_out_edge_pruning', 's6_5_orphan_cluster')},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
