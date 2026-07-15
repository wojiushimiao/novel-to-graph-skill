#!/usr/bin/env python3
"""novel-to-graph-skill · v0.5.1 端到端实测验证脚本

验证 v0.5.1 两大新功能在真实小说数据（全职法师）上的表现：
- B1: 骨架审查与重做（evaluate_skeleton_quality + rebuild_skeleton）
- B2: 人物小传构建（prepare_character_synthesis + create_synthesis_entity）

数据源:
- 322 个真实 LLM distill 摘要（S2 阶段输出）
- 310 个真实 LLM 实体提取输出（S3 阶段输出）

无 LLM 调用：复用已有 LLM 输出，仅执行工具链。
"""
from __future__ import annotations

import sys
import json
import logging
from pathlib import Path
from collections import Counter

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-to-graph-skill')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
DISTILL_DIR = WORKSPACE / 'distill'
LLM_OUTPUTS_DIR = WORKSPACE / 'llm_outputs'

sys.path.insert(0, str(SKILL_DIR))

from tools.semantic_clusterer import cluster_summaries
from tools.timeline_skeleton_builder import build_skeleton_incremental, Skeleton
from tools.graph_builder import (
    evaluate_skeleton_quality,
    rebuild_skeleton,
    SKELETON_QUALITY,
    REBUILD_THRESHOLDS,
    build_evolves_to_relations,
)
from tools.character_synthesizer import (
    prepare_character_synthesis,
    create_synthesis_entity,
)
from tools.models import Entity, Relation

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('e2e_v051')


def sep(title: str) -> None:
    print(f"\n{'='*60}\n{title}\n{'='*60}")


# ═══════════════════════════════════════════════════════════
# 阶段 1: S2.5 端到端验证（B1 骨架审查与重做）
# ═══════════════════════════════════════════════════════════

def load_distill_summaries() -> list[dict]:
    """加载 322 个 distill 摘要，转换为 cluster_summaries 输入格式。"""
    sep("阶段1.1 加载真实 LLM distill 摘要")
    summaries = []
    for f in sorted(DISTILL_DIR.glob('distill_*.json')):
        data = json.loads(f.read_text(encoding='utf-8'))
        summaries.append({
            'chunk_index': data.get('chunk_index', len(summaries)),
            'summary': data.get('raw_summary', ''),
            'timestamp': data.get('chunk_index', len(summaries)),
        })
    print(f"加载 {len(summaries)} 个摘要")
    print(f"首条摘要预览: {summaries[0]['summary'][:100]}...")
    return summaries


def phase1_skeleton_pipeline(summaries: list[dict]) -> None:
    """S2.5 完整管线：cluster → skeleton → evaluate → rebuild。"""
    sep("阶段1.2 基线聚类（thresholds=None，默认 0.55/0.70/0.65）")

    # 基线聚类（embedding 不可用，走 Jaccard 兜底）
    cluster_base = cluster_summaries(summaries, use_embedding=False)
    t_main_base = cluster_base['t_main_candidates']
    modules_base = cluster_base['module_candidates']
    print(f"基线 T_main 候选数: {len(t_main_base)}")
    print(f"基线 E_module 候选数: {len(modules_base)}")
    if t_main_base:
        print(f"基线 T_main 分布（前5）: {[(c['id'], c.get('range'), c.get('stage')) for c in t_main_base[:5]]}")

    sep("阶段1.3 基线骨架构建")
    try:
        skeleton_base = build_skeleton_incremental(cluster_base)
        print(f"基线骨架: T_main 卷数={len(skeleton_base.t_main_volumes)}")
        print(f"基线骨架: E_module 数={len(skeleton_base.e_modules)}")
        print(f"基线骨架: T_main 关系数={len(skeleton_base.t_main_relations)}")
        print(f"基线骨架: HAS_MODULE 关系数={len(skeleton_base.has_module_relations)}")
        print(f"基线骨架: fallback_used={getattr(skeleton_base, 'fallback_used', 'N/A')}")
    except Exception as e:
        print(f"基线骨架构建失败: {e}")
        skeleton_base = None

    if skeleton_base is None:
        print("无法继续评估，退出阶段1")
        return

    sep("阶段1.4 骨架质量评估（evaluate_skeleton_quality）")
    # evaluate_skeleton_quality 直接使用 skeleton 内部数据
    # entities/relations 参数用于评估 T_branch 覆盖率（S6 阶段才有 T_branch 关系）
    # S2.5 阶段只有 HAS_MODULE 关系，无 T_branch，覆盖率预期为 0
    mock_relations = []
    for rel in skeleton_base.has_module_relations:
        mock_relations.append(Relation(
            source_id=rel.source_id,
            target_id=rel.target_id,
            relation_type="T_branch",
        ))

    print(f"骨架 T_main 卷实体数: {len(skeleton_base.t_main_volumes)}")
    print(f"骨架 E_module 实体数: {len(skeleton_base.e_modules)}")
    print(f"模拟 T_branch 关系数: {len(mock_relations)}")

    quality = evaluate_skeleton_quality(skeleton_base, [], mock_relations)
    print(f"\n骨架质量评估结果:")
    print(f"  t_main_count: {quality.get('t_main_count')} (min={SKELETON_QUALITY['t_main_min']}, ideal={SKELETON_QUALITY['t_main_ideal_min']}-{SKELETON_QUALITY['t_main_ideal_max']}, max={SKELETON_QUALITY['t_main_max']})")
    print(f"  avg_modules_per_vol: {quality.get('avg_modules_per_vol')} (min={SKELETON_QUALITY['modules_per_vol_min']}, ideal={SKELETON_QUALITY['modules_per_vol_ideal']}, max={SKELETON_QUALITY['modules_per_vol_max']})")
    print(f"  t_branch_coverage: {quality.get('t_branch_coverage')} (min={SKELETON_QUALITY['t_branch_coverage_min']})")
    print(f"  issues: {quality.get('issues', [])}")
    print(f"  verdict: {quality.get('verdict')}")

    sep("阶段1.5 骨架重做（rebuild_skeleton with REBUILD_THRESHOLDS）")
    print(f"REBUILD_THRESHOLDS: {REBUILD_THRESHOLDS}")
    print(f"  (提高阈值 = 更多边界 = 更细颗粒度)")

    rebuilt = rebuild_skeleton(
        summaries=summaries,
        adjusted_thresholds=REBUILD_THRESHOLDS,
        original_skeleton=skeleton_base,
    )
    print(f"\n重做骨架结果:")
    print(f"  T_main 卷数: {len(skeleton_base.t_main_volumes)} → {len(rebuilt.t_main_volumes)}")
    print(f"  E_module 数: {len(skeleton_base.e_modules)} → {len(rebuilt.e_modules)}")
    print(f"  T_main 关系数: {len(skeleton_base.t_main_relations)} → {len(rebuilt.t_main_relations)}")
    print(f"  HAS_MODULE 关系数: {len(skeleton_base.has_module_relations)} → {len(rebuilt.has_module_relations)}")

    # 判断是否降级
    is_fallback = (
        len(rebuilt.t_main_volumes) == len(skeleton_base.t_main_volumes)
        and len(rebuilt.e_modules) == len(skeleton_base.e_modules)
    )
    if is_fallback:
        print(f"  ⚠️ 重做结果与基线相同（可能降级返回 original_skeleton）")
    else:
        print(f"  ✅ 重做成功，骨架已更新")

    sep("阶段1.6 对比聚类：自定义阈值 vs 基线")
    # 直接用 REBUILD_THRESHOLDS 聚类，对比 t_main_candidates 数量
    cluster_rebuilt = cluster_summaries(summaries, use_embedding=False, thresholds=REBUILD_THRESHOLDS)
    print(f"基线聚类 T_main 候选: {len(t_main_base)}")
    print(f"重做聚类 T_main 候选: {len(cluster_rebuilt['t_main_candidates'])}")
    print(f"基线聚类 E_module 候选: {len(modules_base)}")
    print(f"重做聚类 E_module 候选: {len(cluster_rebuilt['module_candidates'])}")

    if len(cluster_rebuilt['t_main_candidates']) > len(t_main_base):
        print(f"  ✅ 提高阈值后 T_main 候选增加（更细颗粒度，方向正确）")
    elif len(cluster_rebuilt['t_main_candidates']) == len(t_main_base):
        print(f"  ⚠️ T_main 候选数不变（Jaccard 兜底下可能区分度不足）")
    else:
        print(f"  ❌ T_main 候选减少（方向异常，需排查）")


# ═══════════════════════════════════════════════════════════
# 阶段 2: B2 端到端验证（人物小传构建）
# ═══════════════════════════════════════════════════════════

def load_llm_entities() -> list[Entity]:
    """从 414 个 LLM 输出中提取角色实体（多档案并行模拟）。

    LLM 输出格式: {chunk_index, items: [{delta_update: {target_entity_id, updated_fields: {info, new_wiki_relations}}}]}
    角色实体主要出现在 event 的 new_wiki_relations.target 中（C_ 前缀）。

    模拟 v0.5.0 多档案并行：将 chunk_index 映射到 vol_idx（每 50 chunk 一卷），
    为每个角色在每个卷中创建独立档案（C_{name}__T_main_vol_{idx}）。
    """
    sep("阶段2.1 加载真实 LLM 实体提取输出（多档案并行模拟）")
    # 收集每个角色出现在哪些 chunk 中
    char_chunks: dict[str, list[int]] = {}  # {char_name: [chunk_idx, ...]}
    for f in sorted(LLM_OUTPUTS_DIR.glob('chunk_*.json')):
        if '_error' in f.name:
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        chunk_idx = data.get('chunk_index', 0)
        items = data.get('items', [])
        for item in items:
            if not isinstance(item, dict):
                continue
            # 从 delta_update.target_entity_id 提取角色
            delta = item.get('delta_update', {})
            tid = delta.get('target_entity_id', '')
            if tid.startswith('C_'):
                name = tid[2:]
                char_chunks.setdefault(name, []).append(chunk_idx)
            # 从 new_wiki_relations.target 提取角色
            fields = delta.get('updated_fields', {})
            for rel in fields.get('new_wiki_relations', []):
                target = rel.get('target', '')
                if target.startswith('C_'):
                    name = target[2:]
                    char_chunks.setdefault(name, []).append(chunk_idx)

    print(f"独立角色名数: {len(char_chunks)}")

    # 模拟多档案并行：每 50 chunk 一卷，414 chunk ≈ 9 卷
    CHUNKS_PER_VOL = 50
    all_entities: list[Entity] = []
    for name, chunks in char_chunks.items():
        # 计算该角色出现在哪些卷
        vol_set = set()
        for cidx in chunks:
            vol_idx = cidx // CHUNKS_PER_VOL
            vol_set.add(vol_idx)
        # 为每个卷创建一个档案
        for vol_idx in sorted(vol_set):
            entity_id = f"C_{name}__T_main_vol_{vol_idx}"
            all_entities.append(Entity(
                id=entity_id,
                name=name,
                type='character',
                coords={'T': f'vol_{vol_idx}', 'C': name},
                info=f"[模拟] {name} 在第 {vol_idx} 卷的档案（基于 {len([c for c in chunks if c // CHUNKS_PER_VOL == vol_idx])} 个 chunk 提取）",
            ))

    print(f"模拟多档案角色实体: {len(all_entities)} 个")
    multi_vol = sum(1 for n, cs in char_chunks.items() if len(set(c // CHUNKS_PER_VOL for c in cs)) >= 2)
    print(f"多卷角色（≥2 卷）: {multi_vol} 个")
    return all_entities


def phase2_character_synthesis(entities: list[Entity]) -> None:
    """B2 人物小传构建端到端验证。"""
    sep("阶段2.2 角色实体分析")

    # 分析角色 id 格式
    id_patterns = Counter()
    for e in entities:
        if '__T_main_vol_' in e.id:
            id_patterns['v0.5.0_multi_profile'] += 1
        elif e.id.startswith('C_'):
            id_patterns['v0.4_legacy'] += 1
        else:
            id_patterns['other'] += 1
    print(f"角色 id 格式分布: {dict(id_patterns)}")

    # 角色名分布
    name_counts = Counter(e.name for e in entities)
    print(f"独立角色名数: {len(name_counts)}")
    print(f"档案数 Top 10:")
    for name, cnt in name_counts.most_common(10):
        print(f"  {name}: {cnt} 个档案")

    # 统计每个角色的卷分布
    from collections import defaultdict
    char_vols: dict[str, set[int]] = defaultdict(set)
    for e in entities:
        if '__T_main_vol_' in e.id:
            parts = e.id.rsplit('__T_main_vol_', 1)
            name = parts[0][2:]  # 去掉 "C_"
            vol = int(parts[1])
            char_vols[name].add(vol)

    multi_vol_chars = {n: v for n, v in char_vols.items() if len(v) >= 2}
    print(f"\n多卷角色（≥2 卷）: {len(multi_vol_chars)} 个")
    if multi_vol_chars:
        print(f"Top 5 多卷角色:")
        for name, vols in sorted(multi_vol_chars.items(), key=lambda x: -len(x[1]))[:5]:
            print(f"  {name}: {sorted(vols)} ({len(vols)} 卷)")

    sep("阶段2.3 prepare_character_synthesis + build_evolves_to_relations")
    evolves_to_relations = build_evolves_to_relations(entities)
    print(f"evolves_to 关系数: {len(evolves_to_relations)}")

    synthesis_data = prepare_character_synthesis(entities, evolves_to_relations)
    print(f"人物小传数据准备完成: {len(synthesis_data)} 个多卷角色")
    if synthesis_data:
        first = synthesis_data[0]
        print(f"\n首个多卷角色示例:")
        print(f"  name: {first['name']}")
        print(f"  volumes: {len(first['volumes'])} 卷")
        print(f"  vol_indices: {[v['vol_idx'] for v in first['volumes']]}")
        print(f"  首卷 entity_id: {first['volumes'][0]['entity_id']}")
        print(f"  首卷 info 预览: {first['volumes'][0]['info'][:100]}...")

    sep("阶段2.4 create_synthesis_entity")
    if synthesis_data:
        first = synthesis_data[0]
        # 模拟 LLM 生成的人物小传（5 段结构）
        mock_synthesis_info = (
            "【身份概述】莫凡是全职法师的主角，原为水兰中学的学神，穿越到魔法世界后沦为魔法学渣，"
            "后觉醒双系（雷与火）进入天澜魔法高中学习。身份从普通学生转变为魔法师。\n"
            "【性格演变】从自信学神到受嘲讽学渣，莫凡的性格经历了从骄傲到坚韧的转变。"
            "面对阶级压迫，他展现出不屈不挠的意志和逆袭决心。\n"
            "【能力成长】觉醒雷系与火系双系魔法，隐藏雷系。通过不断修炼和实战，"
            "魔法能力逐步提升，从初学者成长为有战斗力的魔法师。\n"
            "【关系网络】与穆白存在嘲讽对立关系，与父亲莫家兴有深厚亲情，"
            "通过穆贺安排进入天澜魔法高中。在学校结识新的同伴。\n"
            "【人物弧光】莫凡的人物弧光是从巅峰跌落谷底后重新崛起的逆袭之路。"
            "从科学世界的学神到魔法世界的学渣，再通过觉醒双系和不懈努力逐步逆袭。"
            "这一弧光体现了面对命运不公时的坚韧和主动改变命运的力量。"
        )
        synthesis_entity = create_synthesis_entity(
            name=first['name'],
            info=mock_synthesis_info,
            volumes_covered=[v['vol_idx'] for v in first['volumes']],
            source_profiles=[v['entity_id'] for v in first['volumes']],
        )
        print(f"synthesis 实体创建成功:")
        print(f"  id: {synthesis_entity.id}")
        print(f"  name: {synthesis_entity.name}")
        print(f"  type: {synthesis_entity.type}")
        print(f"  coords: {synthesis_entity.coords}")
        print(f"  base_info: {synthesis_entity.base_info}")
        print(f"  detail_info.keys: {list(synthesis_entity.detail_info.keys())}")
        print(f"  detail_info.volumes_covered: {synthesis_entity.detail_info.get('volumes_covered')}")
        print(f"  detail_info.source_profiles: {synthesis_entity.detail_info.get('source_profiles')}")
        print(f"  info 长度: {len(synthesis_entity.info)} 字")
        print(f"  info 预览: {synthesis_entity.info[:100]}...")

        # 验证 schema
        from tools.models import CHARACTER_SYNTHESIS_SCHEMA, CHARACTER_SYNTHESIS_TOTAL_MIN, CHARACTER_SYNTHESIS_TOTAL_MAX
        print(f"\n  Schema 验证:")
        print(f"    CHARACTER_SYNTHESIS_SCHEMA: {CHARACTER_SYNTHESIS_SCHEMA}")
        print(f"    TOTAL_MIN: {CHARACTER_SYNTHESIS_TOTAL_MIN}, TOTAL_MAX: {CHARACTER_SYNTHESIS_TOTAL_MAX}")
        print(f"    实际字数: {len(synthesis_entity.info)}")
        if CHARACTER_SYNTHESIS_TOTAL_MIN <= len(synthesis_entity.info) <= CHARACTER_SYNTHESIS_TOTAL_MAX:
            print(f"    ✅ 字数在范围内")
        else:
            print(f"    ⚠️ 字数超出范围")
    else:
        print("无多卷角色，跳过 create_synthesis_entity 验证")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    sep("v0.5.1 端到端实测验证 · 全职法师真实数据")
    print(f"数据源: {WORKSPACE}")
    print(f"distill 文件数: {len(list(DISTILL_DIR.glob('distill_*.json')))}")
    print(f"LLM 输出文件数: {len(list(LLM_OUTPUTS_DIR.glob('chunk_*.json')))}")

    # 阶段 1: S2.5 端到端
    summaries = load_distill_summaries()
    phase1_skeleton_pipeline(summaries)

    # 阶段 2: B2 端到端
    entities = load_llm_entities()
    if entities:
        phase2_character_synthesis(entities)
    else:
        print("\n⚠️ 无角色实体，跳过阶段2")

    sep("v0.5.1 端到端实测验证完成")


if __name__ == '__main__':
    main()
