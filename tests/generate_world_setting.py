#!/usr/bin/env python3
"""生成符合"历史信息统合系统"输出格式的世界设定集

从S7 DB读取轴化后的数据，生成：
1. 时序主轴索引表
2. 时序分支明细表
3. 空间拓扑辅轴
4. 因果辅轴
5. 角色弧光序列
6. 实体档案
"""
from __future__ import annotations

import sys
import os
import json
import sqlite3
from pathlib import Path
from collections import defaultdict

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-to-graph-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
OUTPUT_DIR = WORKSPACE / 'output'
S7_DB_PATH = OUTPUT_DIR / 'full_llm_graph_s7.db'
WORLD_SETTING_PATH = OUTPUT_DIR / 'world_setting_axis.md'
WORLD_SETTING_JSON_PATH = OUTPUT_DIR / 'world_setting_axis.json'

sys.path.insert(0, str(SKILL_DIR))


def load_from_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    entities = []
    for row in conn.execute('SELECT * FROM entities'):
        e = dict(row)
        for k in ('base_info', 'detail_info', 'stitch_tags', 'coords'):
            if e.get(k):
                try:
                    e[k] = json.loads(e[k])
                except:
                    e[k] = {}
        entities.append(e)

    relations = []
    for row in conn.execute('SELECT * FROM wiki_relations'):
        relations.append(dict(row))

    conn.close()
    return entities, relations


def build_indexes(entities, relations):
    """构建各种索引"""
    entity_map = {}
    by_type = defaultdict(list)
    for e in entities:
        entity_map[e['id']] = e
        by_type[e['type']].append(e)

    # 关系索引
    out_edges = defaultdict(list)
    in_edges = defaultdict(list)
    by_rel_type = defaultdict(list)
    for r in relations:
        out_edges[r['source_id']].append(r)
        in_edges[r['target_id']].append(r)
        by_rel_type[r['relation_type']].append(r)

    return entity_map, by_type, out_edges, in_edges, by_rel_type


def generate_world_setting_md(entities, relations, output_path):
    """生成世界设定集 Markdown"""
    entity_map, by_type, out_edges, in_edges, by_rel_type = build_indexes(entities, relations)

    lines = []
    lines.append('# 全职法师 · 世界设定集（历史信息统合系统轴化版）')
    lines.append('')
    lines.append(f'> 生成时间：2026-07-11')
    lines.append(f'> 实体总数：{len(entities)} | 关系总数：{len(relations)}')
    lines.append(f'> 角色：{len(by_type.get("character",[]))} | 事件：{len(by_type.get("event",[]))} | 地点：{len(by_type.get("location",[]))} | 物品：{len(by_type.get("item",[]))} | 规则：{len(by_type.get("rule",[]))} | 系统：{len(by_type.get("system",[]))}')
    lines.append('')

    # ====== 1. 时序主轴索引表 ======
    lines.append('---')
    lines.append('')
    lines.append('## 一、时序主轴索引表')
    lines.append('')
    lines.append('| 顺序 | 事件关键字 | 章节 | 核心角色 | 主题 | 下一主轴事件 |')
    lines.append('|------|-----------|------|----------|------|-------------|')

    t_main_rels = sorted(by_rel_type.get('T_main', []), key=lambda r: r.get('source_chapter', ''))
    t_main_events = set()
    for r in t_main_rels:
        t_main_events.add(r['source_id'])
        t_main_events.add(r['target_id'])

    # 按章节排序主轴事件
    main_events_sorted = []
    for eid in t_main_events:
        if eid in entity_map:
            main_events_sorted.append(entity_map[eid])
    main_events_sorted.sort(key=lambda e: e.get('source_chapter', ''))

    # 构建顺序
    for i, e in enumerate(main_events_sorted[:100]):
        name = e['name']
        chapter = e.get('source_chapter', '?')
        coords = e.get('coords', {})
        if isinstance(coords, str):
            try: coords = json.loads(coords)
            except: coords = {}
        chars = ', '.join(coords.get('C', [])[:3]) if coords.get('C') else '—'
        themes = ', '.join(coords.get('K', [])[:2]) if coords.get('K') else '—'

        # 找下一事件
        next_event = '—'
        for r in out_edges.get(e['id'], []):
            if r['relation_type'] == 'T_main':
                next_name = entity_map.get(r['target_id'], {}).get('name', r['target_id'])
                next_event = next_name
                break

        lines.append(f'| {i+1} | {name} | {chapter} | {chars} | {themes} | {next_event} |')

    lines.append('')
    lines.append(f'> 主轴事件数：{len(main_events_sorted)}')

    # ====== 2. 空间拓扑辅轴 ======
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## 二、空间拓扑辅轴')
    lines.append('')

    # 收集S_topo关系
    s_topo = by_rel_type.get('S_topo', [])
    # 构建地点层级
    location_parents = defaultdict(list)
    location_children = defaultdict(list)
    for r in s_topo:
        if r['source_id'] in entity_map and entity_map[r['source_id']]['type'] == 'location':
            location_children[r['source_id']].append(r['target_id'])
            location_parents[r['target_id']].append(r['source_id'])

    # 找根地点（没有父节点的）
    all_locations = [e for e in entities if e['type'] == 'location']
    location_ids = {e['id'] for e in all_locations}
    root_locations = [lid for lid in location_ids if lid not in location_parents]

    lines.append('### 地点层级树')
    lines.append('')
    for root in root_locations[:20]:
        name = entity_map.get(root, {}).get('name', root)
        lines.append(f'#### {name} ({root})')
        _print_location_tree(root, location_children, entity_map, lines, indent=0, max_depth=3)
        lines.append('')

    # 角色驻留
    lines.append('### 角色驻留')
    lines.append('')
    lines.append('| 角色 | 地点 | 关系描述 |')
    lines.append('|------|------|----------|')
    for r in s_topo:
        if r['source_id'].startswith('C_'):
            char_name = entity_map.get(r['source_id'], {}).get('name', r['source_id'])
            loc_name = entity_map.get(r['target_id'], {}).get('name', r['target_id'])
            desc = r.get('description', '')[:60]
            lines.append(f'| {char_name} | {loc_name} | {desc} |')

    # ====== 3. 因果辅轴 ======
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## 三、因果辅轴')
    lines.append('')
    lines.append('| 原因事件 | 关系 | 结果事件 | 描述 |')
    lines.append('|----------|------|----------|------|')

    a_causal = by_rel_type.get('A_causal', [])
    for r in a_causal[:100]:
        src_name = entity_map.get(r['source_id'], {}).get('name', r['source_id'])
        tgt_name = entity_map.get(r['target_id'], {}).get('name', r['target_id'])
        rel_type = '导致' if r['relation_type'] == 'A_causal' else r['relation_type']
        desc = r.get('description', '')[:80]
        lines.append(f'| {src_name} | {rel_type} | {tgt_name} | {desc} |')

    # ====== 4. 角色弧光序列 ======
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## 四、角色弧光序列')
    lines.append('')

    characters = sorted(by_type.get('character', []), key=lambda e: -len(in_edges.get(e['id'], [])))
    for char in characters[:30]:
        name = char['name']
        char_id = char['id']

        # 从detail_info获取弧光
        detail = char.get('detail_info', {})
        if isinstance(detail, str):
            try: detail = json.loads(detail)
            except: detail = {}
        arc = detail.get('character_arc', [])

        # 从入边获取参与的事件
        in_events = []
        for r in in_edges.get(char_id, []):
            if r['relation_type'] in ('T_branch', 'A_arc', 'R_strong', 'T_main', 'A_causal'):
                event_name = entity_map.get(r['source_id'], {}).get('name', r['source_id'])
                if event_name and event_name not in in_events:
                    in_events.append(event_name)

        lines.append(f'### {name} ({char_id})')
        if arc:
            lines.append(f'> 弧光事件：{" → ".join(arc[:10])}')
        if in_events:
            lines.append(f'> 参与事件（{len(in_events)}个）：{", ".join(in_events[:15])}')
        lines.append(f'> 入边数：{len(in_edges.get(char_id, []))} | 出边数：{len(out_edges.get(char_id, []))}')
        lines.append('')

    # ====== 5. 实体档案 ======
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## 五、关键实体档案')
    lines.append('')

    # 5.1 角色档案（Top 20）
    lines.append('### 5.1 角色档案')
    lines.append('')
    for char in characters[:20]:
        char_id = char['id']
        name = char['name']
        base_info = char.get('base_info', {})
        if isinstance(base_info, str):
            try: base_info = json.loads(base_info)
            except: base_info = {}
        detail = char.get('detail_info', {})
        if isinstance(detail, str):
            try: detail = json.loads(detail)
            except: detail = {}

        lines.append(f'#### {name}')
        lines.append(f'- **ID**：{char_id}')
        lines.append(f'- **首次出现**：{char.get("source_chapter", "未知")}')
        lines.append(f'- **重要度**：high={base_info.get("importance_scores",[]).count("high") if isinstance(base_info.get("importance_scores"), list) else 0}')

        # 出边
        out = out_edges.get(char_id, [])
        if out:
            lines.append('- **出边**：')
            for r in out[:5]:
                tgt = entity_map.get(r['target_id'], {}).get('name', r['target_id'])
                lines.append(f'  - [{r["relation_type"]}] → {tgt}')

        # 入边（关联角色）
        in_rel = [r for r in in_edges.get(char_id, []) if r['source_id'].startswith('C_')]
        if in_rel:
            lines.append('- **关联角色**：')
            for r in in_rel[:5]:
                src = entity_map.get(r['source_id'], {}).get('name', r['source_id'])
                lines.append(f'  - [{r["relation_type"]}] ← {src}')

        # 信息
        info = detail.get('info', '')
        if info:
            lines.append(f'- **详细信息**：{info[:300]}...' if len(info) > 300 else f'- **详细信息**：{info}')
        lines.append('')

    # 5.2 关键事件档案
    lines.append('### 5.2 关键事件档案')
    lines.append('')
    top_events = sorted(by_type.get('event', []), key=lambda e: -len(in_edges.get(e['id'], [])))[:20]
    for evt in top_events:
        eid = evt['id']
        name = evt['name']
        detail = evt.get('detail_info', {})
        if isinstance(detail, str):
            try: detail = json.loads(detail)
            except: detail = {}

        lines.append(f'#### {name}')
        lines.append(f'- **ID**：{eid}')
        lines.append(f'- **章节**：{evt.get("source_chapter", "未知")}')

        # 参与者
        participants = [r for r in out_edges.get(eid, []) if r['target_id'].startswith('C_')]
        if participants:
            chars = [entity_map.get(r['target_id'], {}).get('name', r['target_id']) for r in participants[:10]]
            lines.append(f'- **参与者**：{", ".join(chars)}')

        # 因果
        causes = [r for r in out_edges.get(eid, []) if r['relation_type'] == 'A_causal']
        if causes:
            effects = [entity_map.get(r['target_id'], {}).get('name', r['target_id']) for r in causes[:5]]
            lines.append(f'- **导致**：{", ".join(effects)}')

        info = detail.get('info', '')
        if info:
            lines.append(f'- **详情**：{info[:300]}...' if len(info) > 300 else f'- **详情**：{info}')
        lines.append('')

    # 5.3 地点档案
    lines.append('### 5.3 地点档案')
    lines.append('')
    top_locations = sorted(by_type.get('location', []), key=lambda e: -len(in_edges.get(e['id'], [])))[:15]
    for loc in top_locations:
        lid = loc['id']
        name = loc['name']
        detail = loc.get('detail_info', {})
        if isinstance(detail, str):
            try: detail = json.loads(detail)
            except: detail = {}

        lines.append(f'#### {name}')
        lines.append(f'- **ID**：{lid}')

        # 驻留角色
        residents = [r for r in in_edges.get(lid, []) if r['source_id'].startswith('C_')]
        if residents:
            chars = [entity_map.get(r['source_id'], {}).get('name', r['source_id']) for r in residents[:10]]
            lines.append(f'- **驻留角色**：{", ".join(chars)}')

        # 子地点
        children = [r for r in out_edges.get(lid, []) if r['target_id'].startswith('L_')]
        if children:
            child_names = [entity_map.get(r['target_id'], {}).get('name', r['target_id']) for r in children[:10]]
            lines.append(f'- **包含地点**：{", ".join(child_names)}')
        lines.append('')

    # 5.4 规则档案
    lines.append('### 5.4 规则档案')
    lines.append('')
    rules = by_type.get('rule', [])[:15]
    for rule in rules:
        rid = rule['id']
        name = rule['name']
        detail = rule.get('detail_info', {})
        if isinstance(detail, str):
            try: detail = json.loads(detail)
            except: detail = {}

        lines.append(f'#### {name}')
        lines.append(f'- **ID**：{rid}')
        info = detail.get('info', '')
        if info:
            lines.append(f'- **规则内容**：{info[:300]}...' if len(info) > 300 else f'- **规则内容**：{info}')

        # 约束实体
        bindings = [r for r in out_edges.get(rid, [])]
        if bindings:
            targets = [entity_map.get(r['target_id'], {}).get('name', r['target_id']) for r in bindings[:10]]
            lines.append(f'- **约束实体**：{", ".join(targets)}')
        lines.append('')

    # ====== 6. 统计摘要 ======
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## 六、统计摘要')
    lines.append('')
    lines.append(f'| 指标 | 值 |')
    lines.append(f'|------|-----|')
    lines.append(f'| 实体总数 | {len(entities)} |')
    lines.append(f'| 关系总数 | {len(relations)} |')
    lines.append(f'| 角色 | {len(by_type.get("character",[]))} |')
    lines.append(f'| 事件 | {len(by_type.get("event",[]))} |')
    lines.append(f'| 地点 | {len(by_type.get("location",[]))} |')
    lines.append(f'| 物品 | {len(by_type.get("item",[]))} |')
    lines.append(f'| 规则 | {len(by_type.get("rule",[]))} |')
    lines.append(f'| 系统 | {len(by_type.get("system",[]))} |')

    # 关系类型分布
    rel_dist = defaultdict(int)
    for r in relations:
        rel_dist[r['relation_type']] += 1
    lines.append(f'| T_main 主轴 | {rel_dist.get("T_main", 0)} |')
    lines.append(f'| T_branch 分支 | {rel_dist.get("T_branch", 0)} |')
    lines.append(f'| S_topo 空间拓扑 | {rel_dist.get("S_topo", 0)} |')
    lines.append(f'| A_causal 因果 | {rel_dist.get("A_causal", 0)} |')
    lines.append(f'| A_arc 弧光 | {rel_dist.get("A_arc", 0)} |')
    lines.append(f'| R_strong 强关联 | {rel_dist.get("R_strong", 0)} |')

    # 度数统计
    out_deg = defaultdict(int)
    in_deg = defaultdict(int)
    for r in relations:
        out_deg[r['source_id']] += 1
        in_deg[r['target_id']] += 1
    max_out = max(out_deg.values()) if out_deg else 0
    max_in = max(in_deg.values()) if in_deg else 0
    max_out_eid = max(out_deg, key=out_deg.get) if out_deg else ''
    max_in_eid = max(in_deg, key=in_deg.get) if in_deg else ''
    lines.append(f'| 最大出度 | {max_out} ({entity_map.get(max_out_eid, {}).get("name", max_out_eid)}) |')
    lines.append(f'| 最大入度 | {max_in} ({entity_map.get(max_in_eid, {}).get("name", max_in_eid)}) |')

    content = '\n'.join(lines)
    output_path.write_text(content, encoding='utf-8')
    print(f'世界设定集已生成: {output_path} ({len(content)} 字符)')
    return content


def _print_location_tree(loc_id, children_map, entity_map, lines, indent, max_depth):
    if indent >= max_depth:
        return
    name = entity_map.get(loc_id, {}).get('name', loc_id)
    prefix = '  ' * indent + '- '
    children = children_map.get(loc_id, [])
    if children:
        for child in children[:10]:
            child_name = entity_map.get(child, {}).get('name', child)
            lines.append(f'{prefix}{child_name} ({child})')
            _print_location_tree(child, children_map, entity_map, lines, indent + 1, max_depth)


def main():
    print('=== 生成世界设定集（历史信息统合系统轴化版） ===\n')

    entities, relations = load_from_db(S7_DB_PATH)
    print(f'加载: {len(entities)} 实体, {len(relations)} 关系')

    # 生成 Markdown
    md_content = generate_world_setting_md(entities, relations, WORLD_SETTING_PATH)

    print(f'\n输出文件:')
    print(f'  Markdown: {WORLD_SETTING_PATH} ({WORLD_SETTING_PATH.stat().st_size/1024:.1f}KB)')


if __name__ == '__main__':
    main()