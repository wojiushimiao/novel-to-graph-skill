#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-C3 timeline_skeleton_builder.py v0.4.1 重写测试

锚定: v0.4.1_plan_final.md §T-C3
检查点:
  CP-C3.1: 增量模式产出 5-20 个 T_main 卷
  CP-C3.2: 每卷 E_module ≤8 个
  CP-C3.3: 动态调整后无断裂 T_main 链
  CP-C3.4: 向后兼容（原有 build_skeleton 接口不变）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 tools 目录加入路径（novel-analysis-skill 目录名含连字符，无法作为 Python 包）
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from models import (  # noqa: E402
    Entity,
    Relation,
)
from timeline_skeleton_builder import (  # noqa: E402
    build_skeleton,
    build_skeleton_incremental,
    adjust_skeleton,
    finalize_skeleton,
    Skeleton,
)


# ─── 测试数据构造工具 ───────────────────────────────────────

def _make_cluster_results(
    t_main_count: int,
    module_count: int,
    chunks_per_t_main: int = 10,
) -> dict:
    """构造 cluster_summaries 风格的 cluster_results 输入。

    Args:
        t_main_count: T_main 卷候选数量
        module_count: E_module 候选总数
        chunks_per_t_main: 每卷覆盖的 chunk 数（用于划分模块归属）

    Returns:
        形如 cluster_summaries() 输出的字典
    """
    t_main_candidates = []
    for i in range(t_main_count):
        start = i * chunks_per_t_main
        end = start + chunks_per_t_main - 1
        t_main_candidates.append({
            "id": f"T_main_vol_{i}",
            "name": f"剧情卷_{i + 1}",
            "range": [start, end],
            "start_chunk": start,
            "end_chunk": end,
            "theme": f"主题_{i}",
            "stage": "发展",
        })

    module_candidates = []
    # 将 module_count 个 E_module 均匀分布到所有 T_main 卷范围内
    total_chunks = t_main_count * chunks_per_t_main
    if t_main_count > 0:
        chunks_per_module = max(1, total_chunks // module_count) if module_count > 0 else chunks_per_t_main
        for i in range(module_count):
            start = i * chunks_per_module
            end = min(start + chunks_per_module - 1, total_chunks - 1)
            if start >= total_chunks:
                start = total_chunks - 1
                end = start
            module_candidates.append({
                "id": f"E_module_candidate_{i}",
                "name": f"剧情模块_{i + 1}",
                "range": [start, end],
                "start_chunk": start,
                "end_chunk": end,
                "theme": f"子主题_{i}",
                "stage": "",
            })

    return {
        "t_main_candidates": t_main_candidates,
        "module_candidates": module_candidates,
        "clusters": [],
    }


# ─── CP-C3.1: 增量模式产出 5-20 个 T_main 卷 ───────────────

class TestIncrementalBuildVolumes:
    """验证 build_skeleton_incremental 产出 5-20 个 T_main 卷。"""

    def test_normal_range_eight_volumes(self):
        """8 个候选 → 8 个 T_main 卷（落在 5-20 范围内，原样输出）。"""
        cluster_results = _make_cluster_results(t_main_count=8, module_count=16)
        skeleton = build_skeleton_incremental(cluster_results)
        assert isinstance(skeleton, Skeleton)
        assert 5 <= len(skeleton.t_main_volumes) <= 20
        assert len(skeleton.t_main_volumes) == 8

    def test_lower_bound_five_volumes(self):
        """5 个候选 → 5 个 T_main 卷（边界值）。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        assert len(skeleton.t_main_volumes) == 5

    def test_upper_bound_twenty_volumes(self):
        """20 个候选 → 20 个 T_main 卷（边界值）。"""
        cluster_results = _make_cluster_results(t_main_count=20, module_count=40)
        skeleton = build_skeleton_incremental(cluster_results)
        assert len(skeleton.t_main_volumes) == 20

    def test_below_lower_bound_expanded_to_five(self):
        """3 个候选 → 扩展至 5 个 T_main 卷（不满足下限）。"""
        cluster_results = _make_cluster_results(t_main_count=3, module_count=6)
        skeleton = build_skeleton_incremental(cluster_results)
        assert len(skeleton.t_main_volumes) >= 5, "低于 5 个候选时应扩展至 5 个"

    def test_above_upper_bound_merged_to_twenty(self):
        """25 个候选 → 合并至 20 个 T_main 卷（超过上限）。"""
        cluster_results = _make_cluster_results(t_main_count=25, module_count=50)
        skeleton = build_skeleton_incremental(cluster_results)
        assert len(skeleton.t_main_volumes) <= 20, "超过 20 个候选时应合并至 20 个以内"

    def test_t_main_entity_type_correct(self):
        """T_main 卷实体的 type 为 'T_main'。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        for vol in skeleton.t_main_volumes:
            assert vol.type == "T_main"

    def test_t_main_volume_has_coords_T(self):
        """T_main 卷实体的 coords.T 字段为自身 ID。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        for vol in skeleton.t_main_volumes:
            assert vol.coords.get("T") == vol.id

    def test_t_main_volume_chain_sequential(self):
        """T_main 卷间时序关系构成连续链（vol_0→vol_1→...→vol_N-1）。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        # T_main 关系数量 = 卷数 - 1
        assert len(skeleton.t_main_relations) == len(skeleton.t_main_volumes) - 1
        # 链式连接：第 i 条关系 source = vol[i], target = vol[i+1]
        for i, rel in enumerate(skeleton.t_main_relations):
            assert rel.source_id == skeleton.t_main_volumes[i].id
            assert rel.target_id == skeleton.t_main_volumes[i + 1].id


# ─── CP-C3.2: 每卷 E_module ≤8 个 ─────────────────────────

class TestEModuleCountPerVolume:
    """验证每个 T_main 卷关联的 E_module 数量 ≤8。"""

    def test_normal_distribution_under_eight(self):
        """8 个 T_main 卷 + 16 个 E_module（每卷平均 2 个）→ 每卷 ≤8。"""
        cluster_results = _make_cluster_results(t_main_count=8, module_count=16, chunks_per_t_main=20)
        skeleton = build_skeleton_incremental(cluster_results)
        # 统计每个 T_main 卷的 E_module 数量
        volume_to_modules: dict[str, int] = {vol.id: 0 for vol in skeleton.t_main_volumes}
        for rel in skeleton.has_module_relations:
            if rel.source_id in volume_to_modules:
                volume_to_modules[rel.source_id] += 1
        for vol_id, count in volume_to_modules.items():
            assert count <= 8, f"卷 {vol_id} 含 {count} 个 E_module，超过上限 8"

    def test_over_eight_modules_merged(self):
        """1 个 T_main 卷 + 20 个 E_module → 合并至 ≤8 个 E_module。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=50, chunks_per_t_main=40)
        skeleton = build_skeleton_incremental(cluster_results)
        # 验证每个卷的 E_module 数量 ≤8
        volume_to_modules: dict[str, int] = {vol.id: 0 for vol in skeleton.t_main_volumes}
        for rel in skeleton.has_module_relations:
            if rel.source_id in volume_to_modules:
                volume_to_modules[rel.source_id] += 1
        for vol_id, count in volume_to_modules.items():
            assert count <= 8, f"卷 {vol_id} 含 {count} 个 E_module，应合并至 ≤8"

    def test_e_module_entity_type_correct(self):
        """E_module 实体的 type 为 'E_module'。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        for mod in skeleton.e_modules:
            assert mod.type == "E_module"

    def test_has_module_relation_type(self):
        """T_main → E_module 的 relation_type 为 'HAS_MODULE'。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        for rel in skeleton.has_module_relations:
            assert rel.relation_type == "HAS_MODULE"


# ─── CP-C3.3: 动态调整后无断裂 T_main 链 ──────────────────

class TestAdjustSkeleton:
    """验证 adjust_skeleton 动态调整后 T_main 链无断裂。"""

    def test_adjust_appends_new_volume(self):
        """追加新 cluster 后，T_main 链延伸且无断裂。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        original_count = len(skeleton.t_main_volumes)

        # 构造追加 cluster：接续原 skeleton 末尾
        new_cluster = _make_cluster_results(t_main_count=2, module_count=4, chunks_per_t_main=10)
        # 调整 start_chunk 使其接续原末尾
        offset = skeleton.t_main_volumes[-1].base_info.get("end_chunk", 49) + 1
        for cand in new_cluster["t_main_candidates"]:
            cand["start_chunk"] += offset
            cand["end_chunk"] += offset
            cand["range"] = [cand["start_chunk"], cand["end_chunk"]]
        for cand in new_cluster["module_candidates"]:
            cand["start_chunk"] += offset
            cand["end_chunk"] += offset
            cand["range"] = [cand["start_chunk"], cand["end_chunk"]]

        adjusted = adjust_skeleton(skeleton, new_cluster)
        assert len(adjusted.t_main_volumes) >= original_count
        # 验证 T_main 链无断裂：关系数 = 卷数 - 1
        assert len(adjusted.t_main_relations) == len(adjusted.t_main_volumes) - 1

    def test_adjust_no_broken_chain(self):
        """调整后 T_main 链无断裂：每条关系 source/target 连续。"""
        cluster_results = _make_cluster_results(t_main_count=6, module_count=12)
        skeleton = build_skeleton_incremental(cluster_results)

        # 多次调整
        current = skeleton
        for _ in range(3):
            new_cluster = _make_cluster_results(t_main_count=2, module_count=4, chunks_per_t_main=10)
            offset = current.t_main_volumes[-1].base_info.get("end_chunk", 49) + 1
            for cand in new_cluster["t_main_candidates"]:
                cand["start_chunk"] += offset
                cand["end_chunk"] += offset
                cand["range"] = [cand["start_chunk"], cand["end_chunk"]]
            for cand in new_cluster["module_candidates"]:
                cand["start_chunk"] += offset
                cand["end_chunk"] += offset
                cand["range"] = [cand["start_chunk"], cand["end_chunk"]]
            current = adjust_skeleton(current, new_cluster)

        # 验证链无断裂
        assert len(current.t_main_relations) == len(current.t_main_volumes) - 1
        # 验证连续连接
        for i, rel in enumerate(current.t_main_relations):
            assert rel.source_id == current.t_main_volumes[i].id, (
                f"第 {i} 条关系 source 应为 vol[{i}]，实际为 {rel.source_id}"
            )
            assert rel.target_id == current.t_main_volumes[i + 1].id, (
                f"第 {i} 条关系 target 应为 vol[{i + 1}]，实际为 {rel.target_id}"
            )

    def test_adjust_caps_at_twenty_volumes(self):
        """调整后 T_main 卷数仍 ≤20（超过上限时合并）。"""
        cluster_results = _make_cluster_results(t_main_count=18, module_count=36)
        skeleton = build_skeleton_incremental(cluster_results)

        # 追加 5 个新卷，总数应被合并至 ≤20
        new_cluster = _make_cluster_results(t_main_count=5, module_count=10, chunks_per_t_main=10)
        offset = skeleton.t_main_volumes[-1].base_info.get("end_chunk", 179) + 1
        for cand in new_cluster["t_main_candidates"]:
            cand["start_chunk"] += offset
            cand["end_chunk"] += offset
            cand["range"] = [cand["start_chunk"], cand["end_chunk"]]
        for cand in new_cluster["module_candidates"]:
            cand["start_chunk"] += offset
            cand["end_chunk"] += offset
            cand["range"] = [cand["start_chunk"], cand["end_chunk"]]

        adjusted = adjust_skeleton(skeleton, new_cluster)
        assert len(adjusted.t_main_volumes) <= 20


# ─── CP-C3.4: 向后兼容（原有 build_skeleton 接口不变）──────

class TestBackwardCompatibility:
    """验证原 build_skeleton 接口保持不变（向后兼容）。"""

    def test_build_skeleton_signature_unchanged(self):
        """build_skeleton 仍接受 plot_modules 列表，返回二元组。"""
        plot_modules = [
            {"name": "开局", "chapter_range": [1, 10], "theme": "t1", "stage_position": "开局"},
            {"name": "发展", "chapter_range": [11, 20], "theme": "t2", "stage_position": "发展"},
            {"name": "高潮", "chapter_range": [21, 30], "theme": "t3", "stage_position": "高潮"},
        ]
        result = build_skeleton(plot_modules)
        # 必须返回二元组（不是 Skeleton）
        assert isinstance(result, tuple)
        assert len(result) == 2
        entities, relations = result
        assert isinstance(entities, list)
        assert isinstance(relations, list)

    def test_build_skeleton_returns_E_module_entities(self):
        """build_skeleton 仍返回 E_module 类型实体。"""
        plot_modules = [
            {"name": "开局", "chapter_range": [1, 10], "theme": "t1", "stage_position": "开局"},
            {"name": "发展", "chapter_range": [11, 20], "theme": "t2", "stage_position": "发展"},
        ]
        entities, _ = build_skeleton(plot_modules)
        for ent in entities:
            assert ent.type == "E_module"

    def test_build_skeleton_returns_T_main_relations(self):
        """build_skeleton 仍返回 T_main 类型关系（相邻 E_module 连接）。"""
        plot_modules = [
            {"name": "开局", "chapter_range": [1, 10], "theme": "t1", "stage_position": "开局"},
            {"name": "发展", "chapter_range": [11, 20], "theme": "t2", "stage_position": "发展"},
        ]
        _, relations = build_skeleton(plot_modules)
        for rel in relations:
            assert rel.relation_type == "T_main"

    def test_build_skeleton_raises_on_insufficient_modules(self):
        """build_skeleton 仍在模块数 <2 时抛 ValueError。"""
        with pytest.raises(ValueError):
            build_skeleton([])
        with pytest.raises(ValueError):
            build_skeleton([{"name": "x", "chapter_range": [1, 10], "theme": "t", "stage_position": "s"}])


# ─── finalize_skeleton 测试 ────────────────────────────────

class TestFinalizeSkeleton:
    """验证 finalize_skeleton 全书完成后稳定化处理。"""

    def test_finalize_preserves_volume_count(self):
        """finalize 后 T_main 卷数不变。"""
        cluster_results = _make_cluster_results(t_main_count=6, module_count=12)
        skeleton = build_skeleton_incremental(cluster_results)
        original_count = len(skeleton.t_main_volumes)
        finalized = finalize_skeleton(skeleton)
        assert len(finalized.t_main_volumes) == original_count

    def test_finalize_produces_stable_chain(self):
        """finalize 后 T_main 链完整无断裂。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        finalized = finalize_skeleton(skeleton)
        # 链完整：关系数 = 卷数 - 1
        assert len(finalized.t_main_relations) == len(finalized.t_main_volumes) - 1
        # 连续性：每条关系连接相邻卷
        for i, rel in enumerate(finalized.t_main_relations):
            assert rel.source_id == finalized.t_main_volumes[i].id
            assert rel.target_id == finalized.t_main_volumes[i + 1].id

    def test_finalize_returns_skeleton_type(self):
        """finalize 返回 Skeleton 类型。"""
        cluster_results = _make_cluster_results(t_main_count=5, module_count=10)
        skeleton = build_skeleton_incremental(cluster_results)
        finalized = finalize_skeleton(skeleton)
        assert isinstance(finalized, Skeleton)


# ─── 空输入与边界情况 ──────────────────────────────────────

class TestEdgeCases:
    """验证空输入与边界情况。"""

    def test_empty_cluster_results_raises(self):
        """空 cluster_results 抛 ValueError。"""
        empty_results = {"t_main_candidates": [], "module_candidates": [], "clusters": []}
        with pytest.raises(ValueError):
            build_skeleton_incremental(empty_results)

    def test_single_t_main_candidate_expands_to_five(self):
        """1 个 T_main 候选 → 扩展至 5 个。"""
        cluster_results = _make_cluster_results(t_main_count=1, module_count=2, chunks_per_t_main=50)
        skeleton = build_skeleton_incremental(cluster_results)
        assert len(skeleton.t_main_volumes) >= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
