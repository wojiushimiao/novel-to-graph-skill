#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-C4 run_s4_s7_pipeline.py 增量压缩集成测试

锚定: v0.4.1_plan_final.md §T-C4
检查点:
  CP-C4.1: 增量压缩模式产出 T_main 实体 + E_module 实体
  CP-C4.2: T_main 卷数在 5-20 范围内
  CP-C4.3: 降级路径触发时仍能产出有效骨架
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将 tests 目录加入路径
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# 将 tools 目录加入路径
_TOOLS_DIR = _TESTS_DIR.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ─── 测试数据构造 ───────────────────────────────────────────

def _make_summaries(count: int = 20) -> list[dict]:
    """构造 SummaryBuffer.flush() 风格的摘要列表。"""
    return [
        {"chunk_index": i, "summary": f"第{i}段摘要内容，包含剧情发展", "timestamp": 0.0}
        for i in range(count)
    ]


def _make_cluster_results(t_main_count: int = 8, module_count: int = 16) -> dict:
    """构造 cluster_summaries() 风格的 cluster_results。"""
    t_main_candidates = []
    for i in range(t_main_count):
        start = i * 10
        end = start + 9
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
    for i in range(module_count):
        start = i * 5
        end = start + 4
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


# ─── CP-C4.1: 增量压缩模式产出 T_main 实体 + E_module 实体 ─

class TestIncrementalCompressionOutput:
    """验证增量压缩模式产出 T_main 实体和 E_module 实体。"""

    def test_s2_5_build_skeleton_incremental_function_exists(self):
        """s2_5_build_skeleton_incremental 函数存在且可调用。"""
        import run_s4_s7_pipeline
        assert hasattr(run_s4_s7_pipeline, "s2_5_build_skeleton_incremental")
        assert callable(run_s4_s7_pipeline.s2_5_build_skeleton_incremental)

    def test_incremental_mode_produces_skeleton(self):
        """增量模式产出 Skeleton 对象，含 T_main 实体和 E_module 实体。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(20)
        cluster_results = _make_cluster_results(8, 16)

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.return_value = cluster_results

            # 调用真实的 build_skeleton_incremental（通过 mock 委托）
            from timeline_skeleton_builder import build_skeleton_incremental, Skeleton
            mock_tsb.build_skeleton_incremental.side_effect = build_skeleton_incremental
            mock_tsb.Skeleton = Skeleton

            skeleton, stats = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            # 验证产出 T_main 实体
            assert len(skeleton.t_main_volumes) > 0
            for vol in skeleton.t_main_volumes:
                assert vol.type == "T_main"

            # 验证产出 E_module 实体
            assert len(skeleton.e_modules) > 0
            for mod in skeleton.e_modules:
                assert mod.type == "E_module"

            # 验证统计含卷数和模块数
            assert "t_main_volume_count" in stats
            assert "e_module_count" in stats

    def test_incremental_stats_has_compression_ratio(self):
        """统计含压缩比字段（输入 chunk 数 / 输出 T_main 卷数）。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(20)
        cluster_results = _make_cluster_results(8, 16)

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.return_value = cluster_results
            from timeline_skeleton_builder import build_skeleton_incremental, Skeleton
            mock_tsb.build_skeleton_incremental.side_effect = build_skeleton_incremental
            mock_tsb.Skeleton = Skeleton

            _, stats = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            assert "compression_ratio" in stats
            assert stats["compression_ratio"] > 0


# ─── CP-C4.2: T_main 卷数在 5-20 范围内 ──────────────────

class TestTMainVolumeRange:
    """验证 T_main 卷数在 5-20 范围内。"""

    def test_volumes_in_range_normal(self):
        """正常场景：T_main 卷数在 5-20 范围内。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(50)
        cluster_results = _make_cluster_results(8, 16)

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.return_value = cluster_results
            from timeline_skeleton_builder import build_skeleton_incremental, Skeleton
            mock_tsb.build_skeleton_incremental.side_effect = build_skeleton_incremental
            mock_tsb.Skeleton = Skeleton

            skeleton, stats = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            assert 5 <= len(skeleton.t_main_volumes) <= 20
            assert stats["t_main_volume_count"] == len(skeleton.t_main_volumes)

    def test_volumes_capped_at_twenty(self):
        """超过 20 个候选时合并至 ≤20。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(100)
        cluster_results = _make_cluster_results(25, 50)  # 25 个候选 > 20

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.return_value = cluster_results
            from timeline_skeleton_builder import build_skeleton_incremental, Skeleton
            mock_tsb.build_skeleton_incremental.side_effect = build_skeleton_incremental
            mock_tsb.Skeleton = Skeleton

            skeleton, _ = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            assert len(skeleton.t_main_volumes) <= 20

    def test_volumes_expanded_to_five(self):
        """不足 5 个候选时扩展至 ≥5。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(10)
        cluster_results = _make_cluster_results(3, 6)  # 3 个候选 < 5

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.return_value = cluster_results
            from timeline_skeleton_builder import build_skeleton_incremental, Skeleton
            mock_tsb.build_skeleton_incremental.side_effect = build_skeleton_incremental
            mock_tsb.Skeleton = Skeleton

            skeleton, _ = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            assert len(skeleton.t_main_volumes) >= 5


# ─── CP-C4.3: 降级路径触发时仍能产出有效骨架 ──────────────

class TestFallbackPath:
    """验证增量压缩失败时降级为一次性模式。"""

    def test_fallback_to_build_skeleton_on_failure(self):
        """增量压缩失败时降级为 build_skeleton 一次性模式。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(20)

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            # cluster_summaries 抛出异常，触发降级
            mock_sc.cluster_summaries.side_effect = RuntimeError("embedding model not available")

            # build_skeleton 作为降级路径
            from models import Entity, Relation
            mock_entities = [Entity(id=f"E_module_{i}", name=f"模块{i}", type="E_module") for i in range(5)]
            mock_relations = [
                Relation(source_id=f"E_module_{i}", target_id=f"E_module_{i+1}", relation_type="T_main")
                for i in range(4)
            ]
            mock_tsb.build_skeleton.return_value = (mock_entities, mock_relations)

            skeleton, stats = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            # 降级路径应产出有效骨架
            assert stats["fallback_used"] is True
            assert stats["t_main_volume_count"] > 0 or len(skeleton.e_modules) > 0

    def test_fallback_stats_marked(self):
        """降级路径触发的统计标记 fallback_used=True。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(10)

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.side_effect = RuntimeError("fail")
            from models import Entity, Relation
            mock_tsb.build_skeleton.return_value = (
                [Entity(id="E_module_0", name="m0", type="E_module"),
                 Entity(id="E_module_1", name="m1", type="E_module")],
                [Relation(source_id="E_module_0", target_id="E_module_1", relation_type="T_main")],
            )

            _, stats = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            assert stats["fallback_used"] is True

    def test_no_fallback_when_successful(self):
        """增量压缩成功时 fallback_used=False。"""
        import run_s4_s7_pipeline

        summaries = _make_summaries(20)
        cluster_results = _make_cluster_results(8, 16)

        with patch("run_s4_s7_pipeline.semantic_clusterer") as mock_sc, \
             patch("run_s4_s7_pipeline.timeline_skeleton_builder") as mock_tsb:

            mock_sc.cluster_summaries.return_value = cluster_results
            from timeline_skeleton_builder import build_skeleton_incremental, Skeleton
            mock_tsb.build_skeleton_incremental.side_effect = build_skeleton_incremental
            mock_tsb.Skeleton = Skeleton

            _, stats = run_s4_s7_pipeline.s2_5_build_skeleton_incremental(
                summaries=summaries,
                use_embedding=False,
            )

            assert stats["fallback_used"] is False


# ─── pipeline_stats 集成验证 ──────────────────────────────

class TestPipelineStatsIntegration:
    """验证 pipeline_stats 含 T_main 归纳统计字段。"""

    def test_compute_skeleton_stats_function_exists(self):
        """compute_skeleton_stats 函数存在且可调用。"""
        import run_s4_s7_pipeline
        assert hasattr(run_s4_s7_pipeline, "compute_skeleton_stats")
        assert callable(run_s4_s7_pipeline.compute_skeleton_stats)

    def test_skeleton_stats_has_required_fields(self):
        """compute_skeleton_stats 返回的 dict 含必要字段。"""
        import run_s4_s7_pipeline
        from timeline_skeleton_builder import build_skeleton_incremental

        cluster_results = _make_cluster_results(8, 16)
        skeleton = build_skeleton_incremental(cluster_results)

        stats = run_s4_s7_pipeline.compute_skeleton_stats(skeleton, fallback_used=False)

        assert "t_main_volume_count" in stats
        assert "e_module_count" in stats
        assert "compression_ratio" in stats
        assert "fallback_used" in stats
        assert isinstance(stats["fallback_used"], bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
