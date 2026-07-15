#!/usr/bin/env python3
"""novel-analysis-skill · S4-S7 工具链处理脚本

从 LLM 输出 (llm_outputs_full_llm.json) 执行完整工具链处理：
- S4: 清洗校验 (json_cleaner → schema_validator → low_value_filter)
- S5: 规范化写入 DB (quantifier → id_router → entity_merger → db_writer)
- S7: 触发报表 (graph_builder → centrality → community → bridges → orphans → stats → html → export)

S6 (LLM 图遍历审查) 由单独脚本 run_s6_llm_review.py 处理。

输出:
- output/full_llm_graph.db — SQLite 数据库
- output/full_llm_report.html — HTML 报表
- output/full_llm_report.md — Markdown 报表
- output/full_llm_report.json — JSON 报表
- output/pipeline_stats.json — 管线统计
"""
from __future__ import annotations

import sys
import os
import json
import time
import logging
from pathlib import Path
from collections import defaultdict

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
LLM_OUTPUT_FILE = WORKSPACE / 'llm_outputs_full_llm.json'
OUTPUT_DIR = WORKSPACE / 'output'
DB_PATH = OUTPUT_DIR / 'full_llm_graph.db'
HTML_PATH = OUTPUT_DIR / 'full_llm_report.html'
MD_PATH = OUTPUT_DIR / 'full_llm_report.md'
JSON_PATH = OUTPUT_DIR / 'full_llm_report.json'
PIPELINE_STATS = OUTPUT_DIR / 'pipeline_stats.json'

sys.path.insert(0, r'd:\Gaia\06_核心代码')
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
from tools import har_refiner  # v0.4.1: HAR 自洽校验
from tools.schema_validator import strip_src_markers  # v0.4.1: 过程标记剥离
from tools import semantic_clusterer  # v0.4.1: 语义聚类器
from tools import timeline_skeleton_builder  # v0.4.1: 时序骨架构建器
from tools.timeline_skeleton_builder import Skeleton  # v0.4.1: Skeleton 数据结构

# v0.4.1: HAR LLM 客户端（依赖 shared.llm_infra.auxiliary_client）
try:
    from shared.llm_infra.auxiliary_client import call_llm
    _HAS_CALL_LLM = True
except ImportError:
    _HAS_CALL_LLM = False
    call_llm = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('pipeline')


def load_llm_outputs() -> list[dict]:
    """加载 LLM 输出"""
    logger.info(f'加载 LLM 输出: {LLM_OUTPUT_FILE}')
    if not LLM_OUTPUT_FILE.exists():
        raise FileNotFoundError(f'LLM 输出文件不存在: {LLM_OUTPUT_FILE}')
    data = json.loads(LLM_OUTPUT_FILE.read_text(encoding='utf-8'))
    logger.info(f'加载 {len(data)} 条记录')
    return data


def s4_clean_validate(
    items: list[dict],
    enable_har: bool = False,
    chunks: dict[int, str] | None = None,
    llm_client=None,
    har_max_retries: int = 3,
    har_budget_limit: int | None = None,
    har_failure_threshold: float = 0.30,
) -> tuple[list[dict], dict]:
    """S4: 清洗校验

    v0.4.1 升级: 在 S4.2 和 S4.3 之间插入 S4.25 HAR 自洽校验步骤。

    Args:
        items: LLM 输出条目列表
        enable_har: 是否启用 HAR 自洽校验（默认 False，向后兼容）
        chunks: chunk 索引 → 原文文本映射（HAR 必需）
        llm_client: LLM 调用函数（HAR 必需）
        har_max_retries: HAR 单条目最大重抽次数
        har_budget_limit: HAR 预算上限
        har_failure_threshold: HAR 失败率中止阈值

    Returns:
        (过滤后条目列表, HAR 统计信息 dict) 的二元组
        HAR 禁用时返回零值统计
    """
    print('\n=== S4: 清洗校验 ===')

    # S4.1: json_cleaner (LLM 输出已是 JSON 对象，跳过字符串清洗)
    # 但确保每个 item 是 dict
    raw_dicts = [item for item in items if isinstance(item, dict)]
    print(f'[S4.1] json_cleaner: {len(items)} → {len(raw_dicts)} (过滤非字典)')

    # S4.2: schema_validator
    validated = schema_validator.validate(raw_dicts)
    print(f'[S4.2] schema_validator: {len(raw_dicts)} → {len(validated)}')

    # S4.25: HAR 自洽校验（v0.4.1 新增，可选）
    har_stats = compute_har_stats(None)  # 默认零值
    if enable_har and llm_client is not None and chunks is not None:
        validated, har_stats = s4_25_har_refine(
            validated,
            chunks=chunks,
            llm_client=llm_client,
            max_retries=har_max_retries,
            budget_limit=har_budget_limit,
            failure_threshold=har_failure_threshold,
        )
        print(f'[S4.25] har_refiner: total={har_stats["total"]}, '
              f'success={har_stats["success"]}, failed={har_stats["failed"]}, '
              f'budget_used={har_stats["budget_used"]}, aborted={har_stats["aborted"]}')
    elif enable_har:
        print('[S4.25] har_refiner: 跳过（缺少 llm_client 或 chunks）')

    # S4.25b: 剥离 [src:chunk_NNN] 过程校验标记（v0.4.1 新增，S5 入库前）
    validated = strip_src_markers_in_items(validated)
    print(f'[S4.25b] strip_src_markers: 完成 ({len(validated)} 条)')

    # S4.3: low_value_filter
    filtered = low_value_filter.filter(validated)
    print(f'[S4.3] low_value_filter: {len(validated)} → {len(filtered)}')

    return filtered, har_stats


def s4_25_har_refine(
    items: list[dict],
    chunks: dict[int, str],
    llm_client,
    max_retries: int = 3,
    budget_limit: int | None = None,
    failure_threshold: float = 0.30,
) -> tuple[list[dict], dict]:
    """S4.25: HAR 自洽校验步骤（v0.4.1 新增）。

    对 Info 不达标的条目执行递归重抽，含预算上限和中止阈值。
    HAR_FAILED 的条目写入 hint_tags=['HAR_FAILED']，importance 降级为 low。

    Args:
        items: 待校验的条目列表
        chunks: chunk 索引 → 原文文本映射
        llm_client: LLM 调用函数
        max_retries: 单条目最大重抽次数
        budget_limit: 预算上限
        failure_threshold: 失败率中止阈值

    Returns:
        (修正后条目列表, HAR 统计信息 dict)
    """
    refined, stats = har_refiner.refine_info(
        entries=items,
        chunks=chunks,
        llm_client=llm_client,
        max_retries=max_retries,
        budget_limit=budget_limit,
        failure_threshold=failure_threshold,
    )
    return refined, stats


def strip_src_markers_in_items(items: list[dict]) -> list[dict]:
    """剥离所有条目 info 中的 [src:chunk_NNN] 过程校验标记（v0.4.1 新增）。

    S5 入库前调用，确保最终输出无 src 标记残留。
    畸形标记（如 [src:chunk_] 无数字）保留供调试。

    Args:
        items: 待处理的条目列表

    Returns:
        处理后的条目列表（原列表不被修改，返回新列表）
    """
    cleaned: list[dict] = []
    for item in items:
        # 深拷贝避免修改原数据
        new_item = dict(item)
        delta = dict(new_item.get('delta_update', {}))
        updated = dict(delta.get('updated_fields', {}))
        info = updated.get('info', '')
        if info:
            updated['info'] = strip_src_markers(info)
        delta['updated_fields'] = updated
        new_item['delta_update'] = delta
        cleaned.append(new_item)
    return cleaned


def compute_har_stats(har_stats: dict | None) -> dict:
    """计算 HAR 统计信息（v0.4.1 新增）。

    Args:
        har_stats: HAR 自洽校验返回的统计 dict；None 表示 HAR 禁用

    Returns:
        标准化的 HAR 统计 dict，含字段:
        - total: 待重抽条目总数
        - success: 重抽成功数
        - failed: 重抽失败数
        - retries_avg: 平均重试次数
        - budget_used: 已用预算
        - aborted: 是否触发中止
    """
    if har_stats is None:
        return {
            'total': 0,
            'success': 0,
            'failed': 0,
            'retries_avg': 0.0,
            'budget_used': 0,
            'aborted': False,
        }
    return {
        'total': int(har_stats.get('total', 0)),
        'success': int(har_stats.get('success', 0)),
        'failed': int(har_stats.get('failed', 0)),
        'retries_avg': float(har_stats.get('retries_avg', 0.0)),
        'budget_used': int(har_stats.get('budget_used', 0)),
        'aborted': bool(har_stats.get('aborted', False)),
    }


def s2_5_build_skeleton_incremental(
    summaries: list[dict],
    use_embedding: bool = True,
) -> tuple[Skeleton, dict]:
    """S2.5: 增量压缩构建时序骨架（v0.4.1 新增）。

    替代 v0.4.0 一次性章节标题抽样法，采用 RAPTOR 范式增量聚类构建时序骨架。
    失败时降级回 build_skeleton 一次性模式。

    Args:
        summaries: SummaryBuffer.flush() 输出的摘要列表
        use_embedding: 是否使用 embedding 模型；False 强制关键词降级模式

    Returns:
        (Skeleton 实例, 统计信息 dict) 的二元组
        统计字段: t_main_volume_count/e_module_count/compression_ratio/fallback_used
    """
    print('\n=== S2.5: 增量压缩构建时序骨架 ===')
    print(f'[S2.5] 输入摘要数: {len(summaries)}')

    fallback_used = False
    skeleton: Skeleton
    input_count = len(summaries)

    try:
        # Step 1: 语义聚类
        cluster_results = semantic_clusterer.cluster_summaries(
            summaries,
            use_embedding=use_embedding,
        )
        print(f'[S2.5] semantic_clusterer: '
              f'{len(cluster_results["t_main_candidates"])} T_main 候选, '
              f'{len(cluster_results["module_candidates"])} E_module 候选')

        # Step 2: 增量构建骨架
        skeleton = timeline_skeleton_builder.build_skeleton_incremental(cluster_results)
        print(f'[S2.5] build_skeleton_incremental: '
              f'{len(skeleton.t_main_volumes)} 卷, '
              f'{len(skeleton.e_modules)} 个 E_module')

    except Exception as exc:
        # 降级路径：回退到 build_skeleton 一次性模式
        print(f'[S2.5] 增量压缩失败，降级为一次性模式: {exc}')
        logger.warning(f'S2.5 增量压缩失败，降级为一次性模式: {exc}')
        fallback_used = True

        # 构造降级用的 plot_modules（从 summaries 简单切分）
        plot_modules = _summaries_to_plot_modules(summaries)
        if len(plot_modules) >= 2:
            entities, relations = timeline_skeleton_builder.build_skeleton(plot_modules)
            # 包装为 Skeleton 结构（降级模式仅填充 e_modules 和 t_main_module_relations）
            skeleton = Skeleton(
                t_main_volumes=[],
                e_modules=entities,
                t_main_relations=[],
                has_module_relations=[],
                t_main_module_relations=relations,
            )
        else:
            # summaries 不足以构建骨架，返回空 Skeleton
            skeleton = Skeleton()

    stats = compute_skeleton_stats(skeleton, fallback_used=fallback_used, input_count=input_count)
    print(f'[S2.5] 统计: {stats}')
    return skeleton, stats


def _summaries_to_plot_modules(summaries: list[dict]) -> list[dict]:
    """将摘要列表转换为 plot_modules 格式（降级模式用）。

    简单切分：每 5 个摘要为一个模块。
    """
    if not summaries:
        return []
    modules: list[dict] = []
    chunk_per_module = 5
    sorted_summaries = sorted(summaries, key=lambda s: s.get('chunk_index', 0))
    for i in range(0, len(sorted_summaries), chunk_per_module):
        chunk = sorted_summaries[i:i + chunk_per_module]
        start = chunk[0].get('chunk_index', i)
        end = chunk[-1].get('chunk_index', i + len(chunk) - 1)
        modules.append({
            'name': f'模块_{len(modules) + 1}',
            'chapter_range': [start, end],
            'theme': chunk[0].get('summary', '')[:20],
            'stage_position': '发展',
        })
    return modules


def _generate_placeholder_summaries(items: list[dict]) -> list[dict]:
    """从已加载的 LLM 输出条目生成占位摘要（v0.4.1 新增）。

    当 summaries.json 不可用时，从 items 的 info 字段提取摘要信息，
    供 S2.5 增量压缩使用。质量低于 SummaryBuffer 真实输出，但可驱动降级路径。
    """
    summaries: list[dict] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        delta = item.get('delta_update', {})
        if not isinstance(delta, dict):
            delta = {}
        # 尝试从多个字段提取摘要文本
        summary_text = (
            delta.get('summary', '')
            or delta.get('description', '')
            or item.get('title', '')
            or f'chunk_{idx}'
        )
        summaries.append({
            'chunk_index': item.get('chunk_index', idx),
            'summary': summary_text,
        })
    return summaries


def compute_skeleton_stats(
    skeleton: Skeleton,
    fallback_used: bool = False,
    input_count: int = 0,
) -> dict:
    """计算时序骨架归纳统计（v0.4.1 新增）。

    Args:
        skeleton: Skeleton 实例
        fallback_used: 是否使用了降级路径
        input_count: 输入的 chunk/摘要数量（用于计算压缩比）

    Returns:
        统计 dict，含字段:
        - t_main_volume_count: T_main 卷数
        - e_module_count: E_module 实体数
        - has_module_relation_count: HAS_MODULE 关系数
        - t_main_relation_count: T_main 卷间关系数
        - t_main_module_relation_count: E_module 间关系数
        - compression_ratio: 压缩比（input_count / t_main_volume_count）
        - fallback_used: 是否降级
    """
    volume_count = len(skeleton.t_main_volumes)
    compression_ratio = 0.0
    if volume_count > 0 and input_count > 0:
        compression_ratio = input_count / volume_count

    return {
        't_main_volume_count': volume_count,
        'e_module_count': len(skeleton.e_modules),
        'has_module_relation_count': len(skeleton.has_module_relations),
        't_main_relation_count': len(skeleton.t_main_relations),
        't_main_module_relation_count': len(skeleton.t_main_module_relations),
        'compression_ratio': round(compression_ratio, 2),
        'fallback_used': fallback_used,
    }


def convert_to_entities_relations(items: list[dict]) -> tuple[list[Entity], list[Relation]]:
    """将 LLM 输出字典转为 Entity/Relation 对象

    转换规则:
    - 每个 item 的 delta_update.target_entity_id 是主实体
    - coords.C 中的角色也作为实体（如果不存在则创建占位）
    - new_wiki_relations 中的 target 也作为实体
    - 关系: target_entity_id → new_wiki_relations[].target
    """
    entities_map: dict[str, Entity] = {}  # id -> Entity
    relations: list[Relation] = []
    source_chunks: dict[str, str] = {}  # entity_id -> source_chapter

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

        # 主实体
        main_entity = get_or_create_entity(target_id)

        # 更新主实体的信息
        updated_fields = item.get('delta_update', {}).get('updated_fields', {})
        info = updated_fields.get('info', '')

        # 累积 info 到 detail_info
        if info:
            existing_info = main_entity.detail_info.get('info', '')
            if existing_info:
                main_entity.detail_info['info'] = existing_info + '\n\n---\n\n' + info
            else:
                main_entity.detail_info['info'] = info

        # 更新 stitch_tags
        stitch = item.get('stitch', {})
        if stitch:
            for k in ('sigma', 'epsilon', 'kappa'):
                v = stitch.get(k, '')
                if v:
                    existing = main_entity.stitch_tags.get(k, '')
                    if v not in existing:
                        main_entity.stitch_tags[k] = (existing + ' | ' + v).strip(' |') if existing else v

        # 更新 coords
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

        # importance
        importance = item.get('importance', 'low')
        main_entity.base_info.setdefault('importance_scores', []).append(importance)

        # source_chapter
        if source_chapter:
            if not main_entity.source_chapter:
                main_entity.source_chapter = source_chapter

        # 冲突标记
        if item.get('delta_update', {}).get('conflict_detected', False):
            conflict_note = item.get('delta_update', {}).get('conflict_note', '')
            main_entity.base_info.setdefault('conflicts', []).append({
                'chapter': source_chapter,
                'note': conflict_note,
            })

        # 处理 new_wiki_relations
        relations_data = updated_fields.get('new_wiki_relations', [])
        for rel_data in relations_data:
            target = rel_data.get('target', '')
            rel_type = rel_data.get('type', 'relates_to')
            strength = rel_data.get('strength', 'weak')

            if not target:
                continue

            # 确保目标实体存在
            # 推断目标实体 ID
            if target.startswith(('C_', 'L_', 'E_', 'I_', 'R_', 'S_')):
                target_entity_id = target
            else:
                # 根据 rel_type 推断类型
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

    # S5.1: quantifier
    quantified = quantifier.map_importance(items)
    print(f'[S5.1] quantifier: {len(items)} → {len(quantified)}')

    # S5.2: 转换为 Entity/Relation 对象
    entities, relations = convert_to_entities_relations(quantified)
    print(f'[S5.2] 转换: {len(entities)} 实体, {len(relations)} 关系')

    # S5.3: id_router
    id_router.route(entities, conn=None)
    print(f'[S5.3] id_router: 完成')

    # S5.4: entity_merger
    entities, relations = entity_merger.merge(entities, relations)
    print(f'[S5.4] entity_merger: {len(entities)} 实体, {len(relations)} 关系')

    # S5.4b: 过滤引用不存在实体的关系（entity_merger 合并后可能产生悬空引用）
    valid_ids = {e.id for e in entities}
    before_count = len(relations)
    relations = [r for r in relations if r.source_id in valid_ids and r.target_id in valid_ids]
    dropped = before_count - len(relations)
    if dropped > 0:
        print(f'[S5.4b] 关系过滤: {before_count} → {len(relations)} (丢弃 {dropped} 条悬空引用)')

    # S5.5: db_writer
    # 删除旧 DB
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = db_writer.write_all(str(DB_PATH), entities, relations)
    print(f'[S5.5] db_writer: {DB_PATH} ({DB_PATH.stat().st_size/1024/1024:.1f}MB)')
    conn.close()

    return entities, relations


def s7_generate_reports(entities: list[Entity], relations: list[Relation]):
    """S7: 触发报表"""
    print('\n=== S7: 触发报表 ===')

    # S7.1: graph_builder
    graph = graph_builder.build(entities, relations)
    print(f'[S7.1] graph_builder: {graph.number_of_nodes()} 节点, {graph.number_of_edges()} 边')

    # S7.2: centrality_analyzer
    centrality = centrality_analyzer.analyze(graph)
    top_centrality = centrality_analyzer.top_n_all(centrality, n=20)
    print(f'[S7.2] centrality_analyzer: 完成')

    # S7.3: community_detector
    communities = community_detector.detect(graph)
    print(f'[S7.3] community_detector: {len(communities)} 社群')

    # S7.4: bridges_finder
    bridges = bridges_finder.find(graph, communities)
    print(f'[S7.4] bridges_finder: {len(bridges)} 桥接节点')

    # S7.5: orphans_finder
    orphans = orphans_finder.find(graph)
    print(f'[S7.5] orphans_finder: {len(orphans)} 孤儿节点')

    # S7.6: stats_generator
    stats = stats_generator.generate(graph, entities, relations)
    print(f'[S7.6] stats_generator: density={stats["density"]}, avg_degree={stats["avg_degree"]}')

    # 组装 analysis (键名匹配 exporter.to_json 期望)
    analysis = {
        'degree': centrality.get('degree', {}),
        'betweenness': centrality.get('betweenness', {}),
        'eigenvector': centrality.get('eigenvector', {}),
        'communities': communities,
        'bridges': bridges,
        'orphans': orphans,
        'top_centrality': top_centrality,
        # 兼容 html_renderer 可能使用的键
        'degree_centrality': centrality.get('degree', {}),
        'betweenness_centrality': centrality.get('betweenness', {}),
        'eigenvector_centrality': centrality.get('eigenvector', {}),
    }

    # S7.7: html_renderer
    html_path = html_renderer.render(
        graph=graph,
        analysis=analysis,
        stats=stats,
        title='全职法师 · 全量 LLM 抽取报表 (v0.3.0)',
        output_path=HTML_PATH,
    )
    print(f'[S7.7] html_renderer: {html_path} ({HTML_PATH.stat().st_size/1024/1024:.1f}MB)')

    # S7.8: exporter
    md_content = exporter.to_markdown(graph, entities, relations, stats, title='全职法师 · 全量 LLM 抽取')
    MD_PATH.write_text(md_content, encoding='utf-8')
    print(f'[S7.8] exporter.to_markdown: {MD_PATH} ({MD_PATH.stat().st_size/1024:.1f}KB)')

    json_data = exporter.to_json(graph, entities, relations, stats, analysis=analysis)
    JSON_PATH.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[S7.9] exporter.to_json: {JSON_PATH} ({JSON_PATH.stat().st_size/1024/1024:.1f}MB)')

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

    # info 长度统计
    info_lengths = []
    for item in items:
        info = item.get('delta_update', {}).get('updated_fields', {}).get('info', '')
        info_lengths.append(len(info))
    if info_lengths:
        metrics['info_avg_length'] = sum(info_lengths) / len(info_lengths)
        metrics['info_min_length'] = min(info_lengths)
        metrics['info_max_length'] = max(info_lengths)
        metrics['info_qualified_count'] = sum(1 for l in info_lengths if 500 <= l <= 1500)
        metrics['info_qualified_rate'] = metrics['info_qualified_count'] / len(info_lengths)

    # importance 分布
    importance_dist = {'high': 0, 'medium': 0, 'low': 0}
    for item in items:
        imp = item.get('importance', 'low')
        if imp in importance_dist:
            importance_dist[imp] += 1
    metrics['importance_distribution'] = importance_dist

    # 冲突检测
    conflict_count = sum(1 for item in items if item.get('delta_update', {}).get('conflict_detected', False))
    metrics['conflict_count'] = conflict_count
    metrics['conflict_rate'] = conflict_count / len(items) if items else 0

    # 实体类型分布
    type_dist = defaultdict(int)
    for e in entities:
        type_dist[e.type] += 1
    metrics['entity_type_distribution'] = dict(type_dist)

    # 关系类型分布
    rel_dist = defaultdict(int)
    for r in relations:
        rel_dist[r.relation_type] += 1
    metrics['relation_type_distribution'] = dict(rel_dist)

    # 莫凡度数（如果存在）
    mofan_id = 'C_莫凡'
    if mofan_id in [e.id for e in entities]:
        mofan_degree = sum(1 for r in relations if r.source_id == mofan_id or r.target_id == mofan_id)
        metrics['mofan_degree'] = mofan_degree

    # 最大度数
    degree_counter = defaultdict(int)
    for r in relations:
        degree_counter[r.source_id] += 1
        degree_counter[r.target_id] += 1
    if degree_counter:
        metrics['max_degree'] = max(degree_counter.values())
        metrics['max_degree_entity'] = max(degree_counter, key=degree_counter.get)

    return metrics


def main():
    print('=== novel-analysis-skill · S4-S7 工具链处理 ===\n')

    t0 = time.time()

    # 加载 LLM 输出
    items = load_llm_outputs()

    # v0.4.1: S2.5 增量压缩构建时序骨架（失败不影响后续管线）
    try:
        summaries_file = WORKSPACE / 'summaries.json'
        if summaries_file.exists():
            summaries = json.loads(summaries_file.read_text(encoding='utf-8'))
            logger.info(f'从 summaries.json 加载 {len(summaries)} 条摘要')
        else:
            summaries = _generate_placeholder_summaries(items)
            logger.info(f'从 items 生成 {len(summaries)} 条占位摘要')
        skeleton, skeleton_stats = s2_5_build_skeleton_incremental(summaries)
    except Exception as exc:
        logger.warning(f'S2.5 骨架构建失败，继续管线: {exc}')
        skeleton_stats = {'error': str(exc), 'fallback_used': True}

    # v0.4.1: HAR 配置（通过环境变量启用）
    enable_har = os.environ.get('NOVEL_ANALYSIS_ENABLE_HAR', '0') == '1'
    chunks = None
    llm_client = None
    if enable_har:
        # 从 chunks.json 加载 chunk 数据
        chunks_file = WORKSPACE / 'chunks' / 'chunks.json'
        if chunks_file.exists():
            chunks_data = json.loads(chunks_file.read_text(encoding='utf-8'))
            chunks = {c['index']: c['content'] for c in chunks_data if isinstance(c, dict)}
        # LLM client 需要外部注入（此处仅占位）
        # 实际使用时通过环境变量配置 API key 等
        llm_client = _build_llm_client()

    # S4: 清洗校验（v0.4.1: 含 HAR 自洽校验）
    filtered, har_stats = s4_clean_validate(
        items,
        enable_har=enable_har,
        chunks=chunks,
        llm_client=llm_client,
    )

    # S5: 写入 DB
    entities, relations = s5_write_to_db(filtered)

    # S7: 生成报表
    stats, analysis = s7_generate_reports(entities, relations)

    # 计算质量指标
    print('\n=== 质量指标 ===')
    metrics = compute_quality_metrics(filtered, entities, relations, stats)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    # 保存管线统计（v0.4.1: 含 HAR 统计 + S2.5 骨架统计）
    PIPELINE_STATS.write_text(json.dumps({
        'metrics': metrics,
        'har_stats': har_stats,
        'skeleton_stats': skeleton_stats,
        'elapsed_seconds': time.time() - t0,
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n管线统计已保存: {PIPELINE_STATS}')

    elapsed = time.time() - t0
    print(f'\n=== 完成 (耗时 {elapsed:.1f}s) ===')


def _build_llm_client():
    """构建 LLM 客户端（v0.4.1 新增）。

    基于 shared.llm_infra.auxiliary_client.call_llm 构造 HAR 自洽校验所需的
    Callable[[str], str] 适配器。

    环境变量:
        NOVEL_ANALYSIS_HAR_MODEL: 模型名（默认 deepseek-chat）
        NOVEL_ANALYSIS_HAR_TEMPERATURE: 温度参数（默认 0.1）
        NOVEL_ANALYSIS_HAR_TIMEOUT: 超时秒数（默认 60）

    Returns:
        Callable[[str], str] | None: LLM 调用适配器；call_llm 不可用时返回 None
    """
    if not _HAS_CALL_LLM:
        logger.warning('_build_llm_client: call_llm 不可用，HAR 将跳过')
        return None

    model = os.environ.get('NOVEL_ANALYSIS_HAR_MODEL', 'deepseek-chat')
    temperature = float(os.environ.get('NOVEL_ANALYSIS_HAR_TEMPERATURE', '0.1'))
    timeout = float(os.environ.get('NOVEL_ANALYSIS_HAR_TIMEOUT', '60'))

    def _client(prompt: str) -> str:
        messages = [
            {'role': 'system', 'content': '你是严格的语义抽取校验器。'},
            {'role': 'user', 'content': prompt},
        ]
        response = call_llm(
            messages=messages,
            task='novel_har_refine',
            model=model,
            max_tokens=2048,
            temperature=temperature,
            timeout=timeout,
        )
        return response.choices[0].message.content

    return _client


if __name__ == '__main__':
    main()
