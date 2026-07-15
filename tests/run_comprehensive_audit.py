#!/usr/bin/env python3
"""全量审查 + 深度优化脚本

执行:
1. 全量质量审查（实体/关系/坐标/info/图谱）
2. 幽灵节点识别与合并
3. 孤儿节点聚类与合并
4. 统一时序图谱构建
5. 相似节点聚类
6. 六维坐标修正（仅本条目主要信息）
7. 叙事支撑评估与模式对比
8. 生成优化后 DB + 报表 + 对比报告

输出:
- output/full_llm_graph_s7.db — 优化后 DB
- output/s7_audit_report.json — 审查报告
- output/s7_optimized_report.html — 优化后 HTML
- output/s7_optimized_report.md — 优化后 Markdown
"""
from __future__ import annotations

import sys
import os
import json
import time
import sqlite3
import re
import logging
from pathlib import Path
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from typing import Any

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
OUTPUT_DIR = WORKSPACE / 'output'
S6_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s6.db'
S7_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s7.db'
AUDIT_REPORT = OUTPUT_DIR / 's7_audit_report.json'

sys.path.insert(0, str(SKILL_DIR))

from tools.models import Entity, Relation, ENTITY_OUT_EDGE_LIMITS
from tools import (
    graph_builder, centrality_analyzer, community_detector,
    bridges_finder, orphans_finder, stats_generator,
    html_renderer, exporter, db_writer,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('s7_audit')

# ─── 主观修饰词（幽灵节点检测） ───
SUBJECTIVE_WORDS = [
    '震撼', '悲惨', '惊天', '惊心动魄', '紧急', '意外', '清晨', '深夜',
    '最终', '最后', '第一次', '突然', '猛烈', '激烈', '可怕', '惊人',
    '重大', '关键', '重要', '危急', '神秘', '恐怖', '绝境', '奇迹',
    '辉煌', '毁灭', '绝望', '疯狂', '致命', '极限', '巅峰', '终极',
]

# ─── 实体类型中文映射 ───
TYPE_CN = {
    'character': '角色', 'location': '地点', 'event': '事件',
    'item': '物品', 'rule': '规则', 'system': '系统',
    'monster': '魔物', 'knowledge': '知识',
}


def load_from_db(db_path: Path) -> tuple[list[dict], list[dict]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    entities = [dict(r) for r in conn.execute('SELECT * FROM entities')]
    relations = [dict(r) for r in conn.execute('SELECT * FROM wiki_relations')]
    conn.close()
    for e in entities:
        for k in ('base_info', 'detail_info', 'stitch_tags', 'coords'):
            v = e.get(k)
            if v and isinstance(v, str):
                try:
                    e[k] = json.loads(v)
                except:
                    e[k] = {}
            elif v is None:
                e[k] = {}
    return entities, relations


def dict_to_entity(d: dict) -> Entity:
    return Entity(
        id=d['id'], name=d['name'], type=d['type'],
        base_info=d.get('base_info', {}) if isinstance(d.get('base_info'), dict) else {},
        detail_info=d.get('detail_info', {}) if isinstance(d.get('detail_info'), dict) else {},
        stitch_tags=d.get('stitch_tags', {}) if isinstance(d.get('stitch_tags'), dict) else {},
        coords=d.get('coords', {}) if isinstance(d.get('coords'), dict) else {},
        source_chapter=d.get('source_chapter', '') or '',
        char_offset=d.get('char_offset', 0) or 0,
    )


def entity_to_dict(e: Entity) -> dict:
    return {
        'id': e.id, 'name': e.name, 'type': e.type,
        'base_info': e.base_info, 'detail_info': e.detail_info,
        'stitch_tags': e.stitch_tags, 'coords': e.coords,
        'source_chapter': e.source_chapter, 'char_offset': e.char_offset,
    }


def relation_to_dict(r: Relation) -> dict:
    return {
        'source_id': r.source_id, 'target_id': r.target_id,
        'relation_type': r.relation_type, 'strength': r.strength,
        'description': r.description, 'source_chapter': r.source_chapter,
    }


# ═══════════════════════════════════════════════════════════════
# 1. 全量质量审查
# ═══════════════════════════════════════════════════════════════

def audit_quality(entities: list[dict], relations: list[dict]) -> dict:
    """全面质量审查"""
    print('\n' + '='*60)
    print('1. 全量质量审查')
    print('='*60)

    report = {
        'entity_count': len(entities),
        'relation_count': len(relations),
        'entity_types': {},
        'relation_types': {},
        'info_stats': {},
        'coords_stats': {},
        'orphan_analysis': {},
        'ghost_analysis': {},
        'name_quality': {},
        'graph_stats': {},
    }

    # 1.1 实体类型分布
    type_dist = Counter(e['type'] for e in entities)
    report['entity_types'] = dict(type_dist)
    print(f'  实体类型: {dict(type_dist)}')

    # 1.2 关系类型分布
    rel_dist = Counter(r['relation_type'] for r in relations)
    report['relation_types'] = dict(rel_dist)
    print(f'  关系类型: {dict(rel_dist)}')

    # 1.3 info 字段分析
    info_lengths = []
    entities_with_info = 0
    for e in entities:
        di = e.get('detail_info', {})
        if isinstance(di, dict):
            info = di.get('info', '')
            if info:
                info_lengths.append(len(info))
                entities_with_info += 1

    if info_lengths:
        report['info_stats'] = {
            'count': entities_with_info,
            'avg': sum(info_lengths) / len(info_lengths),
            'min': min(info_lengths),
            'max': max(info_lengths),
            'median': sorted(info_lengths)[len(info_lengths)//2],
            'p25': sorted(info_lengths)[len(info_lengths)//4],
            'p75': sorted(info_lengths)[3*len(info_lengths)//4],
            'qualified_500_1500': sum(1 for l in info_lengths if 500 <= l <= 1500),
            'qualified_rate': sum(1 for l in info_lengths if 500 <= l <= 1500) / len(info_lengths),
            'too_short_lt200': sum(1 for l in info_lengths if l < 200),
            'too_long_gt5000': sum(1 for l in info_lengths if l > 5000),
        }
        print(f'  info: avg={report["info_stats"]["avg"]:.0f}, '
              f'达标率={report["info_stats"]["qualified_rate"]:.1%}, '
              f'太短(<200)={report["info_stats"]["too_short_lt200"]}, '
              f'太长(>5000)={report["info_stats"]["too_long_gt5000"]}')

    # 1.4 坐标冗余分析
    coord_redundancy = analyze_coord_redundancy(entities)
    report['coords_stats'] = coord_redundancy
    print(f'  坐标冗余: 平均C={coord_redundancy["avg_C_count"]:.1f}, '
          f'平均E={coord_redundancy["avg_E_count"]:.1f}, '
          f'冗余实体={coord_redundancy["redundant_entities_pct"]:.1%}')

    # 1.5 孤儿分析
    orphan_stats = analyze_orphans(entities, relations)
    report['orphan_analysis'] = orphan_stats
    print(f'  孤儿: {orphan_stats["count"]} ({orphan_stats["pct"]:.1%}), '
          f'微型: {orphan_stats["micro_count"]}')

    # 1.6 幽灵节点分析
    ghost_stats = analyze_ghosts(entities)
    report['ghost_analysis'] = ghost_stats
    print(f'  幽灵候选: {ghost_stats["count"]}')

    # 1.7 命名质量
    name_stats = analyze_names(entities)
    report['name_quality'] = name_stats
    print(f'  命名质量: 过长(>80)={name_stats["name_too_long"]}, '
          f'含主观词={name_stats["name_has_subjective"]}')

    # 1.8 图谱结构
    ent_objs = [dict_to_entity(e) for e in entities]
    rel_objs = [Relation(
        source_id=r['source_id'], target_id=r['target_id'],
        relation_type=r['relation_type'], strength=r.get('strength', 'weak'),
        description=r.get('description', ''), source_chapter=r.get('source_chapter', ''),
    ) for r in relations]
    graph = graph_builder.build(ent_objs, rel_objs)
    stats = stats_generator.generate(graph, ent_objs, rel_objs)
    report['graph_stats'] = {
        'nodes': graph.number_of_nodes(),
        'edges': graph.number_of_edges(),
        'density': stats.get('density', 0),
        'avg_degree': stats.get('avg_degree', 0),
        'isolated': stats.get('isolated_count', 0),
        'components': stats.get('components', 0),
        'largest_component': stats.get('largest_component_size', 0),
    }
    print(f'  图谱: {report["graph_stats"]["nodes"]}节点, '
          f'{report["graph_stats"]["edges"]}边, '
          f'density={report["graph_stats"]["density"]:.4f}, '
          f'components={report["graph_stats"]["components"]}')

    return report


def analyze_coord_redundancy(entities: list[dict]) -> dict:
    """分析坐标冗余度"""
    c_counts, e_counts = [], []
    redundant = 0
    for e in entities:
        coords = e.get('coords', {})
        if isinstance(coords, dict):
            c_list = coords.get('C', [])
            e_list = coords.get('E', [])
            if isinstance(c_list, list):
                c_counts.append(len(c_list))
            if isinstance(e_list, list):
                e_counts.append(len(e_list))
            # 冗余判定：C 坐标包含的不是本实体自己的角色信息
            if isinstance(c_list, list) and len(c_list) > 3:
                redundant += 1

    return {
        'avg_C_count': sum(c_counts) / len(c_counts) if c_counts else 0,
        'avg_E_count': sum(e_counts) / len(e_counts) if e_counts else 0,
        'max_C_count': max(c_counts) if c_counts else 0,
        'max_E_count': max(e_counts) if e_counts else 0,
        'redundant_entities': redundant,
        'redundant_entities_pct': redundant / len(entities) if entities else 0,
    }


def analyze_orphans(entities: list[dict], relations: list[dict]) -> dict:
    """分析孤儿与微型节点"""
    degree = Counter()
    for r in relations:
        degree[r['source_id']] += 1
        degree[r['target_id']] += 1

    orphans = [e for e in entities if degree[e['id']] == 0]
    micro = [e for e in entities if 0 < degree[e['id']] <= 1]

    # 孤儿类型分布
    orphan_types = Counter(e['type'] for e in orphans)

    return {
        'count': len(orphans),
        'pct': len(orphans) / len(entities) if entities else 0,
        'micro_count': len(micro),
        'orphan_types': dict(orphan_types),
        'orphan_examples': [
            {'id': e['id'], 'name': e['name'], 'type': e['type']}
            for e in orphans[:20]
        ],
    }


def analyze_ghosts(entities: list[dict]) -> dict:
    """分析幽灵节点"""
    ghosts = []
    for e in entities:
        for word in SUBJECTIVE_WORDS:
            if word in e['name']:
                ghosts.append({'id': e['id'], 'name': e['name'], 'type': e['type'], 'word': word})
                break
    return {
        'count': len(ghosts),
        'examples': ghosts[:30],
        'by_type': dict(Counter(g['type'] for g in ghosts)),
        'by_word': dict(Counter(g['word'] for g in ghosts)),
    }


def analyze_names(entities: list[dict]) -> dict:
    """分析命名质量"""
    too_long = sum(1 for e in entities if len(e['name']) > 80)
    has_subjective = sum(1 for e in entities if any(w in e['name'] for w in SUBJECTIVE_WORDS))
    return {
        'name_too_long': too_long,
        'name_has_subjective': has_subjective,
        'avg_name_length': sum(len(e['name']) for e in entities) / len(entities) if entities else 0,
    }


# ═══════════════════════════════════════════════════════════════
# 2. 幽灵节点合并
# ═══════════════════════════════════════════════════════════════

def merge_ghost_nodes(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """合并幽灵节点：识别并合并到语义相近的正常节点"""
    print('\n' + '='*60)
    print('2. 幽灵节点合并')
    print('='*60)

    stats = {'identified': 0, 'merged': 0, 'removed': 0, 'details': []}

    # 识别幽灵节点
    ghost_ids = set()
    ghost_map = {}  # ghost_id -> target_id

    for e in entities:
        for word in SUBJECTIVE_WORDS:
            if word in e['name']:
                ghost_ids.add(e['id'])
                # 尝试找到正常节点
                clean_name = e['name'].replace(word, '').strip()
                if clean_name and len(clean_name) >= 2:
                    # 找最匹配的同类实体
                    candidates = [
                        o for o in entities
                        if o['id'] != e['id'] and o['type'] == e['type']
                        and o['id'] not in ghost_ids
                    ]
                    best_match = None
                    best_score = 0
                    for c in candidates:
                        # 名称相似度
                        sim = SequenceMatcher(None, clean_name, c['name']).ratio()
                        if sim > best_score:
                            best_score = sim
                            best_match = c['id']
                    if best_match and best_score > 0.4:
                        ghost_map[e['id']] = best_match
                break

    stats['identified'] = len(ghost_ids)

    # 执行合并：重定向关系，合并 info
    id_map = {}  # old_id -> new_id
    merged_infos = defaultdict(list)  # target_id -> [info_texts]

    for ghost_id, target_id in ghost_map.items():
        id_map[ghost_id] = target_id
        ghost_entity = next((e for e in entities if e['id'] == ghost_id), None)
        if ghost_entity:
            di = ghost_entity.get('detail_info', {})
            if isinstance(di, dict):
                info = di.get('info', '')
                if info:
                    merged_infos[target_id].append(info)

    # 更新实体：合并 info
    for e in entities:
        if e['id'] in merged_infos:
            di = e.get('detail_info', {})
            if isinstance(di, dict):
                existing_info = di.get('info', '')
                new_info = '\n\n---\n\n'.join(merged_infos[e['id']])
                if existing_info:
                    di['info'] = existing_info + '\n\n---\n\n' + new_info
                else:
                    di['info'] = new_info

    # 删除幽灵节点
    remove_ids = set(ghost_map.keys())
    new_entities = [e for e in entities if e['id'] not in remove_ids]

    # 重定向关系
    for r in relations:
        if r['source_id'] in id_map:
            r['source_id'] = id_map[r['source_id']]
        if r['target_id'] in id_map:
            r['target_id'] = id_map[r['target_id']]

    # 去重关系
    seen = set()
    new_relations = []
    for r in relations:
        key = (r['source_id'], r['target_id'], r['relation_type'])
        if key not in seen:
            seen.add(key)
            new_relations.append(r)

    stats['merged'] = len(ghost_map)
    stats['removed'] = len(remove_ids)
    stats['details'] = [{'from': k, 'to': v} for k, v in list(ghost_map.items())[:20]]

    print(f'  识别: {stats["identified"]} 个幽灵节点')
    print(f'  合并: {stats["merged"]} 个 → 正常节点')
    print(f'  删除: {stats["removed"]} 个实体')
    print(f'  实体: {len(entities)} → {len(new_entities)}')
    print(f'  关系: {len(relations)} → {len(new_relations)}')

    return new_entities, new_relations, stats


# ═══════════════════════════════════════════════════════════════
# 3. 孤儿节点聚类与合并
# ═══════════════════════════════════════════════════════════════

def merge_orphan_nodes(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """聚类孤儿节点：按名称相似度+类型+坐标邻接度聚类"""
    print('\n' + '='*60)
    print('3. 孤儿节点聚类与合并')
    print('='*60)

    stats = {'orphans_before': 0, 'clusters': 0, 'merged': 0, 'new_relations': 0}

    # 计算度数
    degree = Counter()
    for r in relations:
        degree[r['source_id']] += 1
        degree[r['target_id']] += 1

    # 识别孤儿
    orphans = [e for e in entities if degree[e['id']] == 0]
    stats['orphans_before'] = len(orphans)
    print(f'  孤儿节点: {len(orphans)}')

    if not orphans:
        return entities, relations, stats

    # 构建实体索引
    entity_map = {e['id']: e for e in entities}

    # 按类型分组孤儿
    orphan_by_type = defaultdict(list)
    for e in orphans:
        orphan_by_type[e['type']].append(e)

    # 为每个类型聚类
    id_map = {}  # old_id -> cluster_id
    cluster_id_counter = 0
    new_entities = []  # 聚类产生的合并节点

    for etype, e_list in orphan_by_type.items():
        if len(e_list) <= 1:
            continue

        # 计算名称相似度矩阵
        n = len(e_list)
        if n > 500:  # 限制规模
            e_list = e_list[:500]

        # 使用简单的名称前缀聚类
        clusters = defaultdict(list)
        for e in e_list:
            # 提取名称中的核心词（去除数字、标点后的前N个字符）
            core = re.sub(r'[0-9\s\-_，。！？、；：""''（）]', '', e['name'])[:8]
            if core:
                clusters[core].append(e)

        # 合并每个聚类
        for core, cluster_items in clusters.items():
            if len(cluster_items) <= 1:
                continue

            # 创建聚类节点
            cluster_id = f'{etype[0].upper()}_cluster_{cluster_id_counter}'
            cluster_id_counter += 1

            # 取第一个作为代表，合并 info
            representative = cluster_items[0].copy()
            all_infos = []
            for item in cluster_items:
                di = item.get('detail_info', {})
                if isinstance(di, dict):
                    info = di.get('info', '')
                    if info:
                        all_infos.append(info)
                id_map[item['id']] = cluster_id

            # 合并 info
            rep_di = representative.get('detail_info', {})
            if isinstance(rep_di, dict):
                existing = rep_di.get('info', '')
                merged_info = '\n\n---\n\n'.join(all_infos)
                if existing:
                    rep_di['info'] = existing + '\n\n---\n\n' + merged_info
                else:
                    rep_di['info'] = merged_info

            representative['id'] = cluster_id
            representative['name'] = f'{representative["name"]}（聚类{len(cluster_items)}个）'
            new_entities.append(representative)
            stats['clusters'] += 1
            stats['merged'] += len(cluster_items)

    # 保留未聚类的孤儿
    clustered_ids = set(id_map.keys())
    new_entities_from_orphans = [e for e in orphans if e['id'] not in clustered_ids]
    new_entities.extend(new_entities_from_orphans)

    # 移除被合并的孤儿，保留非孤儿实体
    remove_ids = set(id_map.keys())
    final_entities = [e for e in entities if e['id'] not in remove_ids]
    final_entities.extend(new_entities)

    # 重定向关系
    for r in relations:
        if r['source_id'] in id_map:
            r['source_id'] = id_map[r['source_id']]
        if r['target_id'] in id_map:
            r['target_id'] = id_map[r['target_id']]

    # 去重
    seen = set()
    final_relations = []
    for r in relations:
        key = (r['source_id'], r['target_id'], r['relation_type'])
        if key not in seen:
            seen.add(key)
            final_relations.append(r)

    print(f'  聚类: {stats["clusters"]} 个聚类')
    print(f'  合并: {stats["merged"]} 个孤儿 → 聚类节点')
    print(f'  实体: {len(entities)} → {len(final_entities)}')
    print(f'  关系: {len(relations)} → {len(final_relations)}')

    return final_entities, final_relations, stats


# ═══════════════════════════════════════════════════════════════
# 4. 统一时序图谱构建
# ═══════════════════════════════════════════════════════════════

def build_unified_timeline(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """构建统一时序图谱：从 T_main + 章节信息构建完整时序线"""
    print('\n' + '='*60)
    print('4. 统一时序图谱构建')
    print('='*60)

    stats = {'t_main_events': 0, 'timeline_stages': 0, 'events_ordered': 0}

    # 提取所有 T_main 关系构建主轴
    t_main_edges = [(r['source_id'], r['target_id']) for r in relations if r['relation_type'] == 'T_main']
    stats['t_main_events'] = len(t_main_edges) + 1

    # 按时序排列事件
    # 构建事件→章节映射
    event_chapter = {}
    for e in entities:
        if e['type'] == 'event':
            chapter = e.get('source_chapter', '')
            event_chapter[e['id']] = chapter

    # 按章节排序事件
    events_with_chapter = [(eid, event_chapter.get(eid, '9999')) for eid in event_chapter]
    events_with_chapter.sort(key=lambda x: _chapter_sort_key(x[1]))

    # 构建时序阶段
    stages = defaultdict(list)
    for eid, chapter in events_with_chapter:
        stage = _extract_stage(chapter)
        stages[stage].append(eid)

    stats['timeline_stages'] = len(stages)
    stats['events_ordered'] = len(events_with_chapter)

    # 为每个阶段的事件串联 T_main
    stage_order = sorted(stages.keys(), key=_stage_sort_key)
    new_relations = []

    for stage in stage_order:
        stage_events = stages[stage]
        if len(stage_events) >= 2:
            for i in range(len(stage_events) - 1):
                sid, tid = stage_events[i], stage_events[i + 1]
                # 检查是否已存在
                exists = any(
                    r for r in relations + new_relations
                    if r['source_id'] == sid and r['target_id'] == tid and r['relation_type'] == 'T_main'
                )
                if not exists:
                    new_relations.append({
                        'source_id': sid, 'target_id': tid,
                        'relation_type': 'T_main', 'strength': 'strong',
                        'description': f'时序主轴串联: {stage}',
                        'source_chapter': event_chapter.get(sid, ''),
                    })

    # 阶段间串联
    for i in range(len(stage_order) - 1):
        prev_stage = stage_order[i]
        next_stage = stage_order[i + 1]
        if stages[prev_stage] and stages[next_stage]:
            bridge = {
                'source_id': stages[prev_stage][-1],
                'target_id': stages[next_stage][0],
                'relation_type': 'T_main', 'strength': 'strong',
                'description': f'阶段过渡: {prev_stage} → {next_stage}',
                'source_chapter': event_chapter.get(stages[prev_stage][-1], ''),
            }
            new_relations.append(bridge)

    print(f'  主轴事件: {stats["t_main_events"]}')
    print(f'  时序阶段: {stats["timeline_stages"]} 个')
    print(f'  新增 T_main: {len(new_relations)} 条')

    return entities, relations + new_relations, stats


def _chapter_sort_key(chapter: str) -> str:
    """章节排序键"""
    m = re.search(r'(\d+)', chapter)
    if m:
        return m.group(1).zfill(6)
    return chapter


def _extract_stage(chapter: str) -> str:
    """从章节提取阶段"""
    m = re.search(r'(\d+)', chapter)
    if not m:
        return '未知'
    num = int(m.group(1))
    if num <= 100:
        return '第一阶段: 博城篇'
    elif num <= 200:
        return '第二阶段: 学院篇'
    elif num <= 400:
        return '第三阶段: 历练篇'
    elif num <= 800:
        return '第四阶段: 古都篇'
    elif num <= 1200:
        return '第五阶段: 国府篇'
    elif num <= 1600:
        return '第六阶段: 世界篇'
    elif num <= 2200:
        return '第七阶段: 黑暗篇'
    elif num <= 2800:
        return '第八阶段: 圣城篇'
    else:
        return '第九阶段: 终章篇'


def _stage_sort_key(stage: str) -> int:
    m = re.search(r'(\d+)', stage)
    return int(m.group(1)) if m else 999


# ═══════════════════════════════════════════════════════════════
# 5. 相似节点聚类
# ═══════════════════════════════════════════════════════════════

def cluster_similar_nodes(entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """相似节点聚类：前缀分桶 + 高相似度合并，避免 O(n²) 全量比对"""
    print('\n' + '='*60)
    print('5. 相似节点聚类')
    print('='*60)

    stats = {'pairs_found': 0, 'merged': 0, 'clusters': 0}

    # 预计算度数索引（避免 N 次扫描）
    degree = Counter()
    for r in relations:
        degree[r['source_id']] += 1
        degree[r['target_id']] += 1

    # 按类型分组
    by_type = defaultdict(list)
    for e in entities:
        by_type[e['type']].append(e)

    id_map = {}
    merge_count = 0

    for etype, e_list in by_type.items():
        if len(e_list) < 2:
            continue

        n = len(e_list)
        print(f'  处理 {TYPE_CN.get(etype, etype)}: {n} 个实体...')

        # 前缀分桶：按名称前 3 个字符分组
        prefix_buckets = defaultdict(list)
        for e in e_list:
            prefix = e['name'][:3] if len(e['name']) >= 3 else e['name']
            prefix_buckets[prefix].append(e)

        bucket_sizes = [len(b) for b in prefix_buckets.values()]
        print(f'    分桶: {len(prefix_buckets)} 桶, 最大桶={max(bucket_sizes)}, 平均={sum(bucket_sizes)/len(bucket_sizes):.1f}')

        # 仅在桶内比较
        comparisons = 0
        for prefix, bucket in prefix_buckets.items():
            bn = len(bucket)
            if bn < 2:
                continue
            for i in range(bn):
                if bucket[i]['id'] in id_map:
                    continue
                for j in range(i + 1, bn):
                    if bucket[j]['id'] in id_map:
                        continue
                    comparisons += 1
                    sim = SequenceMatcher(None, bucket[i]['name'], bucket[j]['name']).ratio()
                    if sim > 0.85:
                        di = degree.get(bucket[i]['id'], 0)
                        dj = degree.get(bucket[j]['id'], 0)
                        if di >= dj:
                            id_map[bucket[j]['id']] = bucket[i]['id']
                            merge_target = bucket[i]['id']
                            source = bucket[j]
                        else:
                            id_map[bucket[i]['id']] = bucket[j]['id']
                            merge_target = bucket[j]['id']
                            source = bucket[i]

                        # 合并 info
                        target = next((e for e in entities if e['id'] == merge_target), None)
                        if target:
                            di_target = target.get('detail_info', {})
                            si = source.get('detail_info', {})
                            if isinstance(di_target, dict) and isinstance(si, dict):
                                existing = di_target.get('info', '')
                                new_info = si.get('info', '')
                                if new_info and new_info not in existing:
                                    di_target['info'] = existing + '\n\n---\n\n' + new_info if existing else new_info

                        merge_count += 1
                        stats['pairs_found'] += 1

        print(f'    实际比较: {comparisons} 次 (全量需 {n*(n-1)//2} 次)')

    # 删除被合并的实体
    remove_ids = set(id_map.keys())
    new_entities = [e for e in entities if e['id'] not in remove_ids]

    # 解析链式合并，确保所有映射指向最终存活实体
    resolved_id_map = _resolve_id_map_chains(id_map)

    # 重定向关系
    for r in relations:
        if r['source_id'] in resolved_id_map:
            r['source_id'] = resolved_id_map[r['source_id']]
        if r['target_id'] in resolved_id_map:
            r['target_id'] = resolved_id_map[r['target_id']]

    # 去重
    seen = set()
    new_relations = []
    for r in relations:
        key = (r['source_id'], r['target_id'], r['relation_type'])
        if key not in seen:
            seen.add(key)
            new_relations.append(r)

    stats['merged'] = merge_count
    stats['clusters'] = len(set(id_map.values()))

    print(f'  发现相似对: {stats["pairs_found"]}')
    print(f'  合并: {stats["merged"]} 个实体')
    print(f'  实体: {len(entities)} → {len(new_entities)}')
    print(f'  关系: {len(relations)} → {len(new_relations)}')

    return new_entities, new_relations, stats


def _resolve_id_map_chains(id_map: dict[str, str]) -> dict[str, str]:
    """解析 id_map 中的链式合并，确保所有映射指向最终存活实体。
    
    例如: {'B': 'A', 'A': 'C'} → {'B': 'C', 'A': 'C'}
    """
    resolved = {}
    for k, v in id_map.items():
        # 沿链追踪到最终目标
        chain = [k]
        current = v
        while current in id_map and current not in chain:
            chain.append(current)
            current = id_map[current]
        resolved[k] = current
    return resolved


# ═══════════════════════════════════════════════════════════════
# 6. 六维坐标修正
# ═══════════════════════════════════════════════════════════════

def fix_coords_scope(entities: list[dict]) -> tuple[list[dict], dict]:
    """修正六维坐标：仅保留本条目主要信息，移除关联实体坐标"""
    print('\n' + '='*60)
    print('6. 六维坐标修正')
    print('='*60)

    stats = {
        'before_avg_C': 0, 'after_avg_C': 0,
        'before_avg_E': 0, 'after_avg_E': 0,
        'cleaned_entities': 0,
    }

    before_c, before_e = [], []
    after_c, after_e = [], []

    for e in entities:
        coords = e.get('coords', {})
        if not isinstance(coords, dict):
            continue

        # 统计 before
        c_list = coords.get('C', [])
        e_list = coords.get('E', [])
        if isinstance(c_list, list):
            before_c.append(len(c_list))
        if isinstance(e_list, list):
            before_e.append(len(e_list))

        # 修正：只保留本实体相关的坐标
        new_coords = {}
        entity_id = e['id']
        entity_type = e['type']

        for dim in ('T', 'L', 'C', 'E', 'K'):
            val = coords.get(dim, [])
            if isinstance(val, str):
                val = [val] if val else []
            if not isinstance(val, list):
                val = []

            if dim == 'C' and entity_type == 'character':
                # 角色实体：只保留自己的坐标
                new_coords[dim] = [entity_id] if entity_id.startswith('C_') else val[:3]
            elif dim == 'E' and entity_type == 'event':
                # 事件实体：只保留自己的坐标
                new_coords[dim] = [entity_id] if entity_id.startswith('E_') else val[:3]
            elif dim == 'L' and entity_type == 'location':
                new_coords[dim] = [entity_id] if entity_id.startswith('L_') else val[:3]
            else:
                # 其他维度：只保留前 5 个最相关的
                new_coords[dim] = val[:5]

        # R 维度保留
        new_coords['R'] = coords.get('R', {})

        e['coords'] = new_coords

        # 统计 after
        ac = new_coords.get('C', [])
        ae = new_coords.get('E', [])
        after_c.append(len(ac) if isinstance(ac, list) else 0)
        after_e.append(len(ae) if isinstance(ae, list) else 0)

        stats['cleaned_entities'] += 1

    stats['before_avg_C'] = sum(before_c) / len(before_c) if before_c else 0
    stats['before_avg_E'] = sum(before_e) / len(before_e) if before_e else 0
    stats['after_avg_C'] = sum(after_c) / len(after_c) if after_c else 0
    stats['after_avg_E'] = sum(after_e) / len(after_e) if after_e else 0

    print(f'  C坐标: {stats["before_avg_C"]:.1f} → {stats["after_avg_C"]:.1f}')
    print(f'  E坐标: {stats["before_avg_E"]:.1f} → {stats["after_avg_E"]:.1f}')
    print(f'  清洗实体: {stats["cleaned_entities"]}')

    return entities, stats


# ═══════════════════════════════════════════════════════════════
# 7. 叙事支撑评估与模式对比
# ═══════════════════════════════════════════════════════════════

def evaluate_narrative_support(entities: list[dict], relations: list[dict],
                               audit: dict) -> dict:
    """评估当前数据结构对叙事和小说编辑的支撑作用"""
    print('\n' + '='*60)
    print('7. 叙事支撑评估与模式对比')
    print('='*60)

    evaluation = {
        'narrative_coverage': {},
        'editing_support': {},
        'mode_comparison': {},
        'recommendations': [],
    }

    # 7.1 叙事覆盖度
    total_chapters = 3233
    chapters_with_events = len(set(e.get('source_chapter', '') for e in entities if e.get('source_chapter')))
    evaluation['narrative_coverage'] = {
        'total_chapters': total_chapters,
        'chapters_with_events': chapters_with_events,
        'coverage_rate': chapters_with_events / total_chapters if total_chapters else 0,
        'event_count': sum(1 for e in entities if e['type'] == 'event'),
        'character_count': sum(1 for e in entities if e['type'] == 'character'),
        'location_count': sum(1 for e in entities if e['type'] == 'location'),
        'avg_events_per_chapter': sum(1 for e in entities if e['type'] == 'event') / max(chapters_with_events, 1),
    }

    print(f'  叙事覆盖: {chapters_with_events}/{total_chapters} 章节 ({evaluation["narrative_coverage"]["coverage_rate"]:.1%})')

    # 7.2 编辑支撑能力
    # 评估维度：人物关系查询、事件回溯、地点追踪、规则查询
    character_rels = sum(1 for r in relations
                         if r['source_id'].startswith('C_') or r['target_id'].startswith('C_'))
    event_rels = sum(1 for r in relations
                     if r['source_id'].startswith('E_') or r['target_id'].startswith('E_'))

    evaluation['editing_support'] = {
        'character_relation_count': character_rels,
        'event_relation_count': event_rels,
        'max_character_degree': audit.get('graph_stats', {}).get('max_degree', 0),
        'can_trace_character_arc': character_rels > 100,
        'can_trace_event_chain': sum(1 for r in relations if r['relation_type'] in ('T_main', 'A_causal')) > 50,
        'can_locate_events': any(e['type'] == 'location' for e in entities),
        'can_query_rules': any(e['type'] == 'rule' for e in entities),
        'info_richness': audit.get('info_stats', {}).get('avg', 0),
    }

    # 7.3 模式对比：信息集成于关系 vs 信息集成于基础信息
    # 模式 A（当前）：info 存储在 detail_info 中，关系仅存类型
    # 模式 B：info 精简到 base_info 摘要，关系携带详细描述
    mode_a_rels_with_desc = sum(1 for r in relations if r.get('description', ''))
    mode_a_avg_desc_len = sum(len(r.get('description', '')) for r in relations) / max(len(relations), 1)

    # 实体 info 大小
    entity_info_sizes = []
    for e in entities:
        di = e.get('detail_info', {})
        if isinstance(di, dict):
            info = di.get('info', '')
            entity_info_sizes.append(len(info))

    mode_a_avg_info = sum(entity_info_sizes) / max(len(entity_info_sizes), 1)

    evaluation['mode_comparison'] = {
        'mode_A_current': {
            'description': '信息描述集成于实体 detail_info，关系仅存类型+强度',
            'avg_entity_info_size': mode_a_avg_info,
            'avg_relation_desc_size': mode_a_avg_desc_len,
            'relations_with_desc': mode_a_rels_with_desc,
            'total_relations': len(relations),
            'storage_entity_kb': sum(entity_info_sizes) / 1024,
            'storage_relation_kb': sum(len(r.get('description', '')) for r in relations) / 1024,
        },
        'mode_B_alternative': {
            'description': '信息描述集成于基础信息 base_info 摘要，关系条目携带详细上下文',
            'estimated_entity_info_size': 500,  # 精简摘要 500 字
            'estimated_relation_desc_size': 300,  # 关系描述 300 字
            'estimated_total_storage_kb': (len(entities) * 500 + len(relations) * 300) / 1024,
        },
        'verdict': '模式 A 更适合大规模知识图谱（关系简洁，查询高效）；模式 B 更适合精读场景（关系携带上下文）',
    }

    print(f'  模式A: 实体平均info={mode_a_avg_info:.0f}字, 关系平均描述={mode_a_avg_desc_len:.0f}字')
    print(f'  模式B估算: 实体500字 + 关系300字 = {evaluation["mode_comparison"]["mode_B_alternative"]["estimated_total_storage_kb"]:.0f}KB')

    # 7.4 建议
    recommendations = []
    if evaluation['narrative_coverage']['coverage_rate'] < 0.5:
        recommendations.append('叙事覆盖度不足50%，建议增加章节覆盖面')
    if audit.get('info_stats', {}).get('qualified_rate', 0) < 0.1:
        recommendations.append('info达标率低于10%，建议优化LLM抽取prompt或增加S6后处理')
    if audit.get('orphan_analysis', {}).get('pct', 0) > 0.3:
        recommendations.append('孤儿节点占比过高，建议增强节点聚类与合并')
    if audit.get('coords_stats', {}).get('redundant_entities_pct', 0) > 0.5:
        recommendations.append('坐标冗余严重，建议限制坐标范围为本实体关联')
    recommendations.append('建议增加角色-事件-地点的三维交叉查询索引')
    recommendations.append('建议实现基于时间线的章节回溯功能')
    evaluation['recommendations'] = recommendations

    for r in recommendations:
        print(f'  建议: {r}')

    return evaluation


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print('='*60)
    print('novel-analysis-skill · S7 全量审查与深度优化')
    print('='*60)

    t0 = time.time()

    # 加载 S6 DB
    print('\n加载 S6 DB...')
    entities, relations = load_from_db(S6_DB_PATH)
    print(f'  实体: {len(entities)}, 关系: {len(relations)}')

    # 1. 全量质量审查
    audit = audit_quality(entities, relations)

    # 2. 幽灵节点合并
    entities, relations, ghost_stats = merge_ghost_nodes(entities, relations)

    # 3. 孤儿节点聚类
    entities, relations, orphan_stats = merge_orphan_nodes(entities, relations)

    # 4. 统一时序图谱
    entities, relations, timeline_stats = build_unified_timeline(entities, relations)

    # 5. 相似节点聚类
    entities, relations, cluster_stats = cluster_similar_nodes(entities, relations)

    # 6. 六维坐标修正
    entities, coord_stats = fix_coords_scope(entities)

    # 7. 叙事支撑评估
    evaluation = evaluate_narrative_support(entities, relations, audit)

    # ─── 写入 S7 DB ───
    print('\n' + '='*60)
    print('写入 S7 优化后 DB...')
    print('='*60)

    ent_objs = [dict_to_entity(e) for e in entities]

    if S7_DB_PATH.exists():
        S7_DB_PATH.unlink()

    # 写入前验证：检查关系是否引用了不存在的实体
    entity_ids = set(e['id'] for e in entities)
    bad_relations = []
    for r in relations:
        if r['source_id'] not in entity_ids:
            bad_relations.append(('source', r['source_id'], r['target_id'], r['relation_type']))
        if r['target_id'] not in entity_ids:
            bad_relations.append(('target', r['target_id'], r['source_id'], r['relation_type']))
    if bad_relations:
        print(f'  ⚠ 发现 {len(bad_relations)} 条引用不存在实体的关系:')
        for br in bad_relations[:10]:
            print(f'    {br[0]}_id={br[1]} 不存在, 另一端={br[2]}, 类型={br[3]}')
        # 过滤掉无效关系
        relations = [r for r in relations if r['source_id'] in entity_ids and r['target_id'] in entity_ids]
        print(f'  过滤后关系: {len(relations)}')
    else:
        print(f'  关系验证通过: 所有 {len(relations)} 条关系引用有效实体')

    rel_objs = [Relation(
        source_id=r['source_id'], target_id=r['target_id'],
        relation_type=r['relation_type'], strength=r.get('strength', 'weak'),
        description=r.get('description', ''), source_chapter=r.get('source_chapter', ''),
    ) for r in relations]

    conn = db_writer.write_all(str(S7_DB_PATH), ent_objs, rel_objs)
    conn.close()
    print(f'  S7 DB: {S7_DB_PATH} ({S7_DB_PATH.stat().st_size/1024/1024:.1f}MB)')

    # ─── 生成优化后报表 ───
    print('\n生成优化后报表...')
    graph = graph_builder.build(ent_objs, rel_objs)
    centrality = centrality_analyzer.analyze(graph)
    top_centrality = centrality_analyzer.top_n_all(centrality, n=20)
    communities = community_detector.detect(graph)
    bridges = bridges_finder.find(graph, communities)
    orphans = orphans_finder.find(graph)
    stats = stats_generator.generate(graph, ent_objs, rel_objs)

    analysis = {
        'degree': centrality.get('degree', {}),
        'betweenness': centrality.get('betweenness', {}),
        'eigenvector': centrality.get('eigenvector', {}),
        'communities': communities, 'bridges': bridges, 'orphans': orphans,
        'top_centrality': top_centrality,
        'degree_centrality': centrality.get('degree', {}),
        'betweenness_centrality': centrality.get('betweenness', {}),
        'eigenvector_centrality': centrality.get('eigenvector', {}),
    }

    html_path = OUTPUT_DIR / 's7_optimized_report.html'
    html_renderer.render(
        graph=graph, analysis=analysis, stats=stats,
        title='全职法师 · 优化后世界设定集 (v0.4.0 · S7 深度优化)',
        output_path=html_path,
    )
    print(f'  HTML: {html_path} ({html_path.stat().st_size/1024/1024:.1f}MB)')

    md_path = OUTPUT_DIR / 's7_optimized_report.md'
    md_content = exporter.to_markdown(
        graph, ent_objs, rel_objs, stats,
        title='全职法师 · 优化后世界设定集 (v0.4.0 · S7 深度优化)'
    )
    md_path.write_text(md_content, encoding='utf-8')
    print(f'  MD: {md_path} ({md_path.stat().st_size/1024:.1f}KB)')

    json_path = OUTPUT_DIR / 's7_optimized_report.json'
    json_data = exporter.to_json(graph, ent_objs, rel_objs, stats, analysis=analysis)
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  JSON: {json_path} ({json_path.stat().st_size/1024/1024:.1f}MB)')

    # ─── 保存完整审查报告 ───
    full_report = {
        'audit': audit,
        'ghost_merge': ghost_stats,
        'orphan_cluster': orphan_stats,
        'timeline': timeline_stats,
        'similar_cluster': cluster_stats,
        'coord_fix': coord_stats,
        'evaluation': evaluation,
        'final_stats': {
            'entities': len(entities),
            'relations': len(relations),
            'graph_nodes': graph.number_of_nodes(),
            'graph_edges': graph.number_of_edges(),
            'density': stats.get('density', 0),
            'avg_degree': stats.get('avg_degree', 0),
            'isolated': stats.get('isolated_count', 0),
            'components': stats.get('components', 0),
        },
        'elapsed_seconds': time.time() - t0,
    }
    AUDIT_REPORT.write_text(json.dumps(full_report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(f'\n审查报告: {AUDIT_REPORT}')

    elapsed = time.time() - t0
    print(f'\n{"="*60}')
    print(f'S7 全量审查完成 (耗时 {elapsed:.1f}s)')
    print(f'最终: {len(entities)} 实体, {len(relations)} 关系')
    print(f'{"="*60}')


if __name__ == '__main__':
    main()