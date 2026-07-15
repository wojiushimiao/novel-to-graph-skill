#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 骨架重做单元测试（v0.5.1 B1）

锚定: graph_builder.rebuild_skeleton
      graph_builder.REBUILD_THRESHOLDS
      timeline_skeleton_builder.Skeleton

覆盖三个场景:
1. 正常重做: 合法摘要 → 返回新 Skeleton（t_main_volumes 非空）
2. 空摘要: summaries=[] → 返回 original_skeleton
3. 重做失败降级: 聚类异常 → 返回 original_skeleton

阈值方向说明:
    代码使用 `if sim < threshold:` 触发边界。
    REBUILD_THRESHOLDS 高于默认值（0.70/0.85/0.80 vs 0.55/0.70/0.65），
    因此更多边界被触发 → 更多 T_main 卷 + 更细 E_module 颗粒度。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from models import Entity  # noqa: E402
from timeline_skeleton_builder import Skeleton  # noqa: E402
from graph_builder import rebuild_skeleton, REBUILD_THRESHOLDS  # noqa: E402


# ─── 测试数据构造 ───────────────────────────────────────

def _make_summaries() -> list[dict]:
    """构造能产生多个 T_main 卷边界的摘要列表。

    8 个摘要覆盖全职法师风格的剧情跨度（觉醒→学院→妖兽袭击→
    世界学府大赛→夺冠→回城→新威胁），相邻 Jaccard 相似度普遍
    低于 REBUILD_THRESHOLDS["temporal"]=0.70，因此触发多个卷边界。
    """
    return [
        {"chunk_index": 0, "summary": "莫凡在博城觉醒魔法天赋，进入魔法学院学习", "timestamp": "ch0"},
        {"chunk_index": 1, "summary": "莫凡在学院中展现出强大实力，击败对手", "timestamp": "ch1"},
        {"chunk_index": 2, "summary": "博城遭遇妖兽袭击，莫凡参与防御战斗", "timestamp": "ch2"},
        {"chunk_index": 3, "summary": "莫凡前往上海参加世界学府大赛", "timestamp": "ch3"},
        {"chunk_index": 4, "summary": "世界学府大赛中莫凡与各国高手交手", "timestamp": "ch4"},
        {"chunk_index": 5, "summary": "莫凡在比赛中突破自我，获得冠军", "timestamp": "ch5"},
        {"chunk_index": 6, "summary": "莫凡回到博城，发现新的威胁出现", "timestamp": "ch6"},
        {"chunk_index": 7, "summary": "莫凡带领团队对抗新威胁，保护城市", "timestamp": "ch7"},
    ]


def _make_original_skeleton() -> Skeleton:
    """构造一个非空的原始骨架（用于降级验证）。"""
    return Skeleton(
        t_main_volumes=[
            Entity(id="T_main_vol_0", name="原始卷_1", type="T_main"),
        ],
    )


# ─── 测试用例 ─────────────────────────────────────────────

class TestRebuildSkeleton:
    """rebuild_skeleton 三场景覆盖。"""

    def test_rebuild_success(self):
        """正常重做: 合法摘要 → 返回新 Skeleton，t_main_volumes 非空。

        REBUILD_THRESHOLDS 的高阈值（temporal=0.70）使相邻摘要
        （Jaccard 普遍 < 0.50）频繁触发边界，产生多个 T_main 卷候选。
        build_skeleton_incremental 保证最终卷数 ∈ [5, 20]。
        """
        summaries = _make_summaries()

        result = rebuild_skeleton(summaries)

        # 返回有效 Skeleton
        assert result is not None
        # T_main 卷数 ∈ [5, 20]（build_skeleton_incremental 的不变式）
        assert 5 <= len(result.t_main_volumes) <= 20, (
            f"T_main 卷数应在 [5, 20] 区间，实际: {len(result.t_main_volumes)}"
        )
        # 至少有一个 E_module 或卷间关系（骨架非空）
        assert len(result.t_main_volumes) > 0

    def test_rebuild_empty_summaries(self):
        """空摘要: summaries=[] → 返回 original_skeleton，不抛异常。"""
        original = _make_original_skeleton()

        result = rebuild_skeleton([], original_skeleton=original)

        # 应返回原始骨架（同一对象）
        assert result is original
        # 原始骨架内容保持不变
        assert len(result.t_main_volumes) == 1
        assert result.t_main_volumes[0].id == "T_main_vol_0"

    def test_rebuild_fallback_on_error(self, monkeypatch):
        """重做失败降级: 聚类抛异常 → 返回 original_skeleton。

        通过 monkeypatch 替换 cluster_summaries 使其抛出异常，
        验证 rebuild_skeleton 的 try/except 降级路径。
        """
        import semantic_clusterer

        def fake_cluster_summaries(*args, **kwargs):
            raise RuntimeError("模拟聚类失败")

        monkeypatch.setattr(semantic_clusterer, "cluster_summaries", fake_cluster_summaries)

        original = _make_original_skeleton()
        summaries = _make_summaries()

        # 不应抛异常，应降级返回原始骨架
        result = rebuild_skeleton(summaries, original_skeleton=original)

        assert result is original
        assert len(result.t_main_volumes) == 1
        assert result.t_main_volumes[0].id == "T_main_vol_0"


# ─── 常量验证 ─────────────────────────────────────────────

class TestRebuildThresholds:
    """REBUILD_THRESHOLDS 常量值验证。"""

    def test_thresholds_higher_than_defaults(self):
        """REBUILD_THRESHOLDS 应高于 semantic_clusterer 默认值。

        代码使用 `sim < threshold` 触发边界，因此更高阈值 = 更多边界。
        """
        from semantic_clusterer import (
            T_MAIN_BOUNDARY_THRESHOLD,
            SCENE_CLUSTER_THRESHOLD,
            ENTITY_CLUSTER_THRESHOLD,
        )

        assert REBUILD_THRESHOLDS["temporal"] > T_MAIN_BOUNDARY_THRESHOLD, (
            "重做 temporal 阈值应高于默认值以产生更多卷边界"
        )
        assert REBUILD_THRESHOLDS["scene"] > SCENE_CLUSTER_THRESHOLD, (
            "重做 scene 阈值应高于默认值以产生更多模块边界"
        )
        assert REBUILD_THRESHOLDS["entity"] > ENTITY_CLUSTER_THRESHOLD, (
            "重做 entity 阈值应高于默认值以产生更多模块边界"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
