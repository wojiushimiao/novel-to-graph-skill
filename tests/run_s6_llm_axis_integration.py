#!/usr/bin/env python3
"""novel-to-graph-skill · S6.5 LLM轴化整合 (历史信息统合系统)

使用"历史信息统合系统-纯LLM整合版.txt"作为LLM系统提示词，
对S6程序化处理后的数据进行智能轴化建模。

处理流程:
1. 加载S6 DB数据
2. 提取Top实体按类型分组
3. 分批发送给LLM，使用历史信息统合系统规则
4. LLM输出结构化轴化决策
5. 应用决策到DB
6. 生成最终报表
"""
from __future__ import annotations

import sys
import os
import json
import time
import logging
import sqlite3
import asyncio
from pathlib import Path
from collections import defaultdict
from typing import Any

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-to-graph-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
OUTPUT_DIR = WORKSPACE / 'output'
S6_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s6.db'
S7_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s7.db'
SYSTEM_PROMPT_PATH = Path(r'd:\Gaia\04_技术文档\历史信息统合系统-纯LLM整合版.txt')

sys.path.insert(0, r'd:\Gaia\06_核心代码')
sys.path.insert(0, str(SKILL_DIR))

os.environ.setdefault('AUXILIARY_PROVIDER', 'deepseek')
os.environ.setdefault('AUXILIARY_MODEL', 'deepseek-chat')

from tools.models import Entity, Relation
from shared.llm_infra.auxiliary_client import call_llm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('s6_llm_axis')

# ─── 配置 ──────────────────────────────────────────────────
LLM_TIMEOUT = 300.0
MAX_TOKENS = 16384
TEMPERATURE = 0.1
BATCH_SIZE = 50  # 每批处理的实体数


def load_system_prompt() -> str:
    """读取历史信息统合系统作为LLM系统提示词"""
    content = SYSTEM_PROMPT_PATH.read_text(encoding='utf-8')
    logger.info(f'系统提示词加载: {len(content)} 字符')
    return content


def load_from_db(db_path: Path) -> tuple[list[dict], list[dict]]:
    """从DB加载实体和关系"""
    logger.info(f'从DB加载: {db_path}')
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


def compute_entity_stats(entities: list[dict], relations: list[dict]) -> dict[str, dict]:
    """计算实体统计信息"""
    # 度数
    degree = defaultdict(int)
    in_deg = defaultdict(int)
    out_deg = defaultdict(int)
    for r in relations:
        degree[r['source_id']] += 1
        degree[r['target_id']] += 1
        out_deg[r['source_id']] += 1
        in_deg[r['target_id']] += 1

    # 重要度
    entity_map = {e['id']: e for e in entities}

    stats = {}
    for e in entities:
        eid = e['id']
        base_info = e.get('base_info', {})
        if isinstance(base_info, str):
            try:
                base_info = json.loads(base_info)
            except:
                base_info = {}

        importance_scores = base_info.get('importance_scores', [])
        high_count = importance_scores.count('high') if isinstance(importance_scores, list) else 0
        medium_count = importance_scores.count('medium') if isinstance(importance_scores, list) else 0

        stats[eid] = {
            'id': eid,
            'name': e['name'],
            'type': e['type'],
            'degree': degree[eid],
            'in_degree': in_deg[eid],
            'out_degree': out_deg[eid],
            'high_count': high_count,
            'medium_count': medium_count,
            'source_chapter': e.get('source_chapter', ''),
            'coords': e.get('coords', {}),
        }
    return stats


def select_top_entities(stats: dict[str, dict], top_n: int = 200) -> list[dict]:
    """选择最重要的实体用于LLM分析"""
    # 按重要度+度数排序
    scored = []
    for eid, s in stats.items():
        score = s['high_count'] * 10 + s['medium_count'] * 3 + s['degree'] * 0.5
        scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    top = [s for _, s in scored[:top_n]]

    # 按类型分组统计
    type_counts = defaultdict(int)
    for s in top:
        type_counts[s['type']] += 1
    logger.info(f'Top {top_n} 实体类型分布: {dict(type_counts)}')
    return top


def build_entity_summary(top_entities: list[dict], relations: list[dict],
                         entity_map: dict[str, dict]) -> str:
    """构建实体摘要文本，供LLM分析"""
    lines = []

    # 按类型分组
    by_type = defaultdict(list)
    for s in top_entities:
        by_type[s['type']].append(s)

    for etype in ['event', 'character', 'location', 'rule', 'item', 'system']:
        items = by_type.get(etype, [])
        if not items:
            continue
        lines.append(f'\n## {etype} 实体 ({len(items)}个)')
        lines.append('')

        for s in items[:50]:  # 每种类型最多50个
            eid = s['id']
            name = s['name']
            # 获取关系
            out_rels = [r for r in relations if r['source_id'] == eid][:10]
            in_rels = [r for r in relations if r['target_id'] == eid][:10]

            lines.append(f'### {name} ({eid})')
            lines.append(f'- 类型: {s["type"]}')
            lines.append(f'- 度数: {s["degree"]} (出{s["out_degree"]}/入{s["in_degree"]})')
            lines.append(f'- 重要度: high={s["high_count"]}, medium={s["medium_count"]}')
            lines.append(f'- 章节: {s.get("source_chapter", "未知")}')

            if out_rels:
                lines.append('- 出边:')
                for r in out_rels:
                    target_name = entity_map.get(r['target_id'], {}).get('name', r['target_id'])
                    lines.append(f'  - [{r["relation_type"]}] → {target_name} ({r["target_id"]})')
            if in_rels:
                lines.append('- 入边:')
                for r in in_rels[:5]:
                    src_name = entity_map.get(r['source_id'], {}).get('name', r['source_id'])
                    lines.append(f'  - [{r["relation_type"]}] ← {src_name} ({r["source_id"]})')
            lines.append('')

    return '\n'.join(lines)


def build_llm_task_prompt(entity_summary: str, task_type: str) -> str:
    """构建LLM任务提示词"""
    prompts = {
        'main_axis': """
## 任务：构建时序主轴 (T_main)

请基于上述实体摘要，按"历史信息统合系统"规则执行以下操作：

1. **识别核心主线事件**：从event实体中，筛选长期价值≥0.85且主题含"主线"的事件
2. **构建主轴链**：按时序将核心主线事件串联为T_main关系链
3. **门控筛选**：长期价值<0.85的事件不作为主轴事件

输出JSON格式：
```json
{
  "main_axis_events": ["E_xxx", "E_yyy", ...],
  "t_main_relations": [
    {"source": "E_xxx", "target": "E_yyy", "description": "原因"}
  ],
  "reasoning": "简要说明主轴筛选逻辑"
}
```
""",
        'spatial_topo': """
## 任务：构建空间拓扑辅轴 (S_topo)

请基于上述实体摘要，按"历史信息统合系统"规则执行以下操作：

1. **建立地点层级**：从location实体中识别大陆→国家→城市→具体场所的层级
2. **构建空间包含关系**：大地域→小地域的S_topo边
3. **角色驻留**：将角色通过S_topo关系关联到其常驻地点

输出JSON格式：
```json
{
  "spatial_hierarchy": {
    "root": "L_大陆名",
    "children": {
      "L_国家": {"children": {"L_城市": {"children": ["L_场所"]}}}
    }
  },
  "s_topo_relations": [
    {"source": "L_大地域", "target": "L_小地域", "description": "空间包含"}
  ],
  "character_locations": [
    {"character": "C_角色", "location": "L_地点", "description": "驻留原因"}
  ],
  "reasoning": "简要说明空间拓扑构建逻辑"
}
```
""",
        'causal_arc': """
## 任务：构建因果辅轴和角色弧光 (A_causal + A_arc)

请基于上述实体摘要，按"历史信息统合系统"规则执行以下操作：

1. **因果链**：识别事件间的因果关系（导致/演化为），建立A_causal边
2. **角色弧光**：为每个主要角色构建时序发展链（按时间排列的事件序列）
3. **扇出控制**：角色出边≤5，事件出边≤3

输出JSON格式：
```json
{
  "a_causal_relations": [
    {"source": "E_原因", "target": "E_结果", "description": "因果描述"}
  ],
  "character_arcs": {
    "C_角色名": ["E_事件1", "E_事件2", "E_事件3", ...]
  },
  "reasoning": "简要说明因果和弧光构建逻辑"
}
```
""",
        'merge_cleanup': """
## 任务：实体合并与清理

请基于上述实体摘要，按"历史信息统合系统"规则执行以下操作：

1. **同名合并**：识别同类型同名的重复实体，指定合并目标
2. **零散节点聚类**：将孤立或微连接的节点聚类到相关主节点
3. **冲突消解**：处理标记了conflict_detected=true的冲突
4. **规则节点建模**：确保规则节点通过引用边连接受约束实体

输出JSON格式：
```json
{
  "merges": [
    {"keep": "E_保留", "remove": ["E_删除1", "E_删除2"], "reason": "原因"}
  ],
  "clusters": [
    {"main": "E_主轴事件", "members": ["E_子事件1", "E_子事件2"], "axis": "T_branch"}
  ],
  "conflict_resolutions": [
    {"entity": "E_冲突实体", "resolution": "解决方案", "new_value": "修正值"}
  ],
  "rule_bindings": [
    {"rule": "R_规则", "targets": ["C_受约束角色", "E_受约束事件"]}
  ]
}
```
""",
    }
    return prompts.get(task_type, prompts['main_axis'])


def _try_fix_truncated_json(text: str) -> str | None:
    """尝试修复被截断的JSON"""
    import re
    # 找到最后一个完整的对象或数组
    # 方法：从后往前找最后一个 } 或 ]，然后验证前面的JSON是否完整
    last_brace = text.rfind('}')
    last_bracket = text.rfind(']')
    if last_brace > last_bracket:
        end = last_brace + 1
    elif last_bracket >= 0:
        end = last_bracket + 1
    else:
        return None

    # 截断到此处并尝试补全
    truncated = text[:end]
    # 计算未闭合的括号
    open_braces = truncated.count('{') - truncated.count('}')
    open_brackets = truncated.count('[') - truncated.count(']')
    # 补全
    truncated += '}' * open_braces + ']' * open_brackets
    # 移除尾部逗号（在}或]之前）
    truncated = re.sub(r',\s*([}\]])', r'\1', truncated)
    return truncated


async def run_llm_axis_task(system_prompt: str, entity_summary: str,
                            task_type: str) -> dict:
    """运行单个LLM轴化任务"""
    task_prompt = build_llm_task_prompt(entity_summary, task_type)
    user_content = entity_summary + '\n\n' + task_prompt

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    logger.info(f'LLM调用 [{task_type}]: {len(user_content)} 字符输入')
    t0 = time.time()

    # spatial_topo 需要更多 tokens
    task_max_tokens = MAX_TOKENS * 2 if task_type == 'spatial_topo' else MAX_TOKENS

    try:
        response = call_llm(
            messages=messages,
            provider='deepseek',
            model='deepseek-chat',
            temperature=TEMPERATURE,
            max_tokens=task_max_tokens,
            timeout=LLM_TIMEOUT,
            task=f's6_axis_{task_type}',
        )
    except Exception as e:
        logger.error(f'LLM调用失败 [{task_type}]: {e}')
        return {'error': str(e), 'task_type': task_type}

    elapsed = time.time() - t0
    logger.info(f'LLM响应 [{task_type}]: {elapsed:.1f}s')

    content = ''
    if hasattr(response, 'choices') and response.choices:
        content = response.choices[0].message.content
    elif hasattr(response, 'content'):
        content = response.content
    elif isinstance(response, str):
        content = response
    else:
        content = str(response)

    # 提取JSON
    try:
        # 尝试找到JSON块
        if '```json' in content:
            json_start = content.index('```json') + 7
            try:
                json_end = content.index('```', json_start)
            except ValueError:
                json_end = len(content)
            content = content[json_start:json_end].strip()
        elif '```' in content:
            json_start = content.index('```') + 3
            try:
                json_end = content.index('```', json_start)
            except ValueError:
                json_end = len(content)
            content = content[json_start:json_end].strip()

        result = json.loads(content)
        result['_raw_response'] = content[:500]
        return result
    except json.JSONDecodeError:
        # 尝试用正则修复不完整的JSON
        logger.warning(f'JSON解析失败 [{task_type}], 尝试修复...')
        # 截断到最后一个完整的数组/对象结束
        fixed = _try_fix_truncated_json(content)
        if fixed:
            try:
                result = json.loads(fixed)
                result['_raw_response'] = content[:500]
                result['_truncated'] = True
                logger.info(f'JSON修复成功 [{task_type}]')
                return result
            except json.JSONDecodeError:
                pass
        logger.warning(f'JSON修复也失败 [{task_type}], 原始响应前500字: {content[:500]}')
        return {'error': 'json_parse_failed', 'raw': content[:2000], 'task_type': task_type}


def apply_axis_decisions(db_path: Path, all_decisions: dict,
                         entities: list[dict], relations: list[dict]) -> tuple[list[dict], list[dict]]:
    """应用LLM的轴化决策到数据"""
    entity_map = {e['id']: e for e in entities}
    relation_set = {(r['source_id'], r['target_id'], r['relation_type']): r for r in relations}

    changes = defaultdict(int)

    # 1. 应用T_main轴决策
    main_axis = all_decisions.get('main_axis', {})
    main_events = set(main_axis.get('main_axis_events', []))
    for rel_data in main_axis.get('t_main_relations', []):
        key = (rel_data['source'], rel_data['target'], 'T_main')
        if key not in relation_set:
            relations.append({
                'source_id': rel_data['source'],
                'target_id': rel_data['target'],
                'relation_type': 'T_main',
                'strength': 'strong',
                'description': rel_data.get('description', ''),
                'source_chapter': '',
            })
            changes['T_main_added'] += 1

    # 标记主轴事件
    for e in entities:
        if e['id'] in main_events:
            coords = e.get('coords', {})
            if isinstance(coords, dict):
                coords['is_main_axis'] = True
                e['coords'] = coords
            changes['main_axis_marked'] += 1

    # 2. 应用空间拓扑
    spatial = all_decisions.get('spatial_topo', {})
    for rel_data in spatial.get('s_topo_relations', []):
        key = (rel_data['source'], rel_data['target'], 'S_topo')
        if key not in relation_set:
            relations.append({
                'source_id': rel_data['source'],
                'target_id': rel_data['target'],
                'relation_type': 'S_topo',
                'strength': 'weak',
                'description': rel_data.get('description', ''),
                'source_chapter': '',
            })
            changes['S_topo_added'] += 1

    for cl in spatial.get('character_locations', []):
        key = (cl['character'], cl['location'], 'S_topo')
        if key not in relation_set:
            relations.append({
                'source_id': cl['character'],
                'target_id': cl['location'],
                'relation_type': 'S_topo',
                'strength': 'weak',
                'description': cl.get('description', ''),
                'source_chapter': '',
            })
            changes['char_location_added'] += 1

    # 3. 应用因果和弧光
    causal = all_decisions.get('causal_arc', {})
    for rel_data in causal.get('a_causal_relations', []):
        key = (rel_data['source'], rel_data['target'], 'A_causal')
        if key not in relation_set:
            relations.append({
                'source_id': rel_data['source'],
                'target_id': rel_data['target'],
                'relation_type': 'A_causal',
                'strength': 'strong',
                'description': rel_data.get('description', ''),
                'source_chapter': '',
            })
            changes['A_causal_added'] += 1

    # 角色弧光存储到实体的detail_info中
    for char_id, arc_events in causal.get('character_arcs', {}).items():
        if char_id in entity_map:
            e = entity_map[char_id]
            detail = e.get('detail_info', {})
            if isinstance(detail, dict):
                detail['character_arc'] = arc_events
                e['detail_info'] = detail
            changes['arc_added'] += 1

    # 4. 应用合并和清理
    merge_cleanup = all_decisions.get('merge_cleanup', {})
    merge_map = {}
    for m in merge_cleanup.get('merges', []):
        keep = m['keep']
        for rm in m.get('remove', []):
            merge_map[rm] = keep
            changes['merged'] += 1

    if merge_map:
        # 更新关系中的引用
        for r in relations:
            r['source_id'] = merge_map.get(r['source_id'], r['source_id'])
            r['target_id'] = merge_map.get(r['target_id'], r['target_id'])

        # 移除被合并的实体
        entities = [e for e in entities if e['id'] not in merge_map]
        changes['entities_removed'] = len(merge_map)

        # 去重关系
        seen = set()
        unique_relations = []
        for r in relations:
            key = (r['source_id'], r['target_id'], r['relation_type'])
            if key not in seen:
                seen.add(key)
                unique_relations.append(r)
        dedup = len(relations) - len(unique_relations)
        relations = unique_relations
        if dedup > 0:
            changes['relations_deduped'] = dedup

    # 5. 应用规则绑定
    for rb in merge_cleanup.get('rule_bindings', []):
        rule_id = rb['rule']
        for target_id in rb.get('targets', []):
            key = (rule_id, target_id, 'R_strong')
            if key not in relation_set:
                relations.append({
                    'source_id': rule_id,
                    'target_id': target_id,
                    'relation_type': 'R_strong',
                    'strength': 'strong',
                    'description': '规则约束',
                    'source_chapter': '',
                })
                changes['rule_binding_added'] += 1

    logger.info(f'轴化决策应用完毕: {dict(changes)}')
    return entities, relations


def write_to_db(db_path: Path, entities: list[dict], relations: list[dict]):
    """写入DB"""
    from tools import db_writer

    if db_path.exists():
        db_path.unlink()

    # 过滤悬空引用（源或目标实体不存在的关系）
    valid_ids = {e['id'] for e in entities}
    before_count = len(relations)
    relations = [r for r in relations
                 if r['source_id'] in valid_ids and r['target_id'] in valid_ids]
    dropped = before_count - len(relations)
    if dropped > 0:
        logger.warning(f'过滤悬空引用: {before_count} → {len(relations)} (丢弃 {dropped} 条)')

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

    conn = db_writer.write_all(str(db_path), ent_objs, rel_objs)
    conn.close()
    logger.info(f'DB写入: {db_path} ({db_path.stat().st_size/1024/1024:.1f}MB)')


def generate_final_reports(db_path: Path, output_dir: Path):
    """生成最终报表"""
    from tools import (
        graph_builder, centrality_analyzer, community_detector,
        bridges_finder, orphans_finder, stats_generator,
        html_renderer, exporter,
    )

    # 加载数据
    entities, relations = load_from_db(db_path)

    ent_objs = []
    for e in entities:
        ent_objs.append(Entity(
            id=e['id'], name=e['name'], type=e['type'],
            base_info=e.get('base_info', {}) if isinstance(e.get('base_info'), dict) else {},
            detail_info=e.get('detail_info', {}) if isinstance(e.get('detail_info'), dict) else {},
            stitch_tags=e.get('stitch_tags', {}) if isinstance(e.get('stitch_tags'), dict) else {},
            coords=e.get('coords', {}) if isinstance(e.get('coords'), dict) else {},
            source_chapter=e.get('source_chapter', ''),
        ))

    rel_objs = []
    for r in relations:
        rel_objs.append(Relation(
            source_id=r['source_id'], target_id=r['target_id'],
            relation_type=r['relation_type'],
            strength=r.get('strength', 'weak'),
            description=r.get('description', ''),
            source_chapter=r.get('source_chapter', ''),
        ))

    # 图分析
    graph = graph_builder.build(ent_objs, rel_objs)
    centrality = centrality_analyzer.analyze(graph)
    communities = community_detector.detect(graph)
    bridges = bridges_finder.find(graph, communities)
    orphans = orphans_finder.find(graph)
    stats = stats_generator.generate(graph, ent_objs, rel_objs)

    analysis = {
        'degree': centrality.get('degree', {}),
        'betweenness': centrality.get('betweenness', {}),
        'eigenvector': centrality.get('eigenvector', {}),
        'communities': communities,
        'bridges': bridges,
        'orphans': orphans,
        'top_centrality': centrality_analyzer.top_n_all(centrality, n=20),
        'degree_centrality': centrality.get('degree', {}),
        'betweenness_centrality': centrality.get('betweenness', {}),
        'eigenvector_centrality': centrality.get('eigenvector', {}),
    }

    # 生成报表
    html_path = output_dir / 'full_llm_report_s7.html'
    md_path = output_dir / 'full_llm_report_s7.md'
    json_path = output_dir / 'full_llm_report_s7.json'

    html_renderer.render(
        graph=graph, analysis=analysis, stats=stats,
        title='全职法师 · 历史信息统合系统 (S7 轴化版)',
        output_path=html_path,
    )

    md_content = exporter.to_markdown(
        graph, ent_objs, rel_objs, stats,
        title='全职法师 · 历史信息统合系统轴化版'
    )
    md_path.write_text(md_content, encoding='utf-8')

    json_data = exporter.to_json(graph, ent_objs, rel_objs, stats, analysis=analysis)
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')

    logger.info(f'报表生成: HTML={html_path.stat().st_size/1024/1024:.1f}MB, '
                f'MD={md_path.stat().st_size/1024:.1f}KB, '
                f'JSON={json_path.stat().st_size/1024/1024:.1f}MB')

    return stats, analysis


async def main_async():
    print('=== novel-to-graph-skill · S6.5 LLM轴化整合 (历史信息统合系统) ===\n')

    t0 = time.time()

    # 1. 加载系统提示词
    system_prompt = load_system_prompt()

    # 2. 加载S6数据
    entities, relations = load_from_db(S6_DB_PATH)
    entity_map = {e['id']: e for e in entities}

    # 3. 计算统计并选择Top实体
    stats = compute_entity_stats(entities, relations)
    top_entities = select_top_entities(stats, top_n=200)

    # 4. 构建实体摘要
    entity_summary = build_entity_summary(top_entities, relations, entity_map)
    logger.info(f'实体摘要: {len(entity_summary)} 字符')

    # 5. 保存摘要供审查
    summary_path = OUTPUT_DIR / 's6_entity_summary.txt'
    summary_path.write_text(entity_summary, encoding='utf-8')
    logger.info(f'实体摘要已保存: {summary_path}')

    # 6. 运行LLM轴化任务
    all_decisions = {}
    tasks = ['main_axis', 'spatial_topo', 'causal_arc', 'merge_cleanup']

    for task_type in tasks:
        print(f'\n--- LLM轴化任务: {task_type} ---')
        result = await run_llm_axis_task(system_prompt, entity_summary, task_type)
        all_decisions[task_type] = result

        if 'error' in result:
            print(f'  [WARN] {task_type} 返回错误: {result["error"]}')
        else:
            print(f'  [OK] {task_type} 完成')
            # 保存中间结果
            task_result_path = OUTPUT_DIR / f's6_llm_{task_type}.json'
            task_result_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
            )

    # 7. 保存所有决策
    decisions_path = OUTPUT_DIR / 's6_llm_all_decisions.json'
    decisions_path.write_text(
        json.dumps(all_decisions, ensure_ascii=False, indent=2, default=str), encoding='utf-8'
    )

    # 8. 应用决策
    print('\n--- 应用LLM轴化决策 ---')
    final_entities, final_relations = apply_axis_decisions(
        S6_DB_PATH, all_decisions, entities, relations
    )
    print(f'  最终: {len(final_entities)} 实体, {len(final_relations)} 关系')

    # 9. 写入S7 DB
    write_to_db(S7_DB_PATH, final_entities, final_relations)

    # 10. 生成最终报表
    print('\n--- 生成最终报表 ---')
    report_stats, analysis = generate_final_reports(S7_DB_PATH, OUTPUT_DIR)

    elapsed = time.time() - t0
    print(f'\n=== S6.5 LLM轴化整合完成 (耗时 {elapsed:.1f}s) ===')
    print(f'最终: {report_stats["node_count"]} 节点, {report_stats["edge_count"]} 边')
    print(f'密度: {report_stats["density"]}, 平均度: {report_stats["avg_degree"]}')
    print(f'孤立节点: {report_stats["isolated_count"]}')

    return all_decisions


def main():
    asyncio.run(main_async())


if __name__ == '__main__':
    main()