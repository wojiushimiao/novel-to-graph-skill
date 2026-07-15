#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-B1.1 semantic_clusterer 阈值参数化测试

锚定: v0.5.1_升级/tasks/plan.md §T-B1.1
检查点:
- thresholds=None 时行为与 v0.5.0 完全一致
- thresholds 自定义值时正确覆盖模块常量
- thresholds 部分覆盖时仅覆盖指定键，其余使用默认值

边界判定逻辑说明:
    代码使用 `if sim < threshold:` 触发边界。
    因此: 更低阈值 → sim < threshold 更难成立 → 更少边界 → 更少(但更大)的聚类。
    更高阈值 → sim < threshold 更易成立 → 更多边界 → 更多(但更小)的聚类。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from semantic_clusterer import (  # noqa: E402
    cluster_summaries,
    T_MAIN_BOUNDARY_THRESHOLD,
    SCENE_CLUSTER_THRESHOLD,
    ENTITY_CLUSTER_THRESHOLD,
)


# ─── 测试数据构造 ───────────────────────────────────────

def _make_summaries(items: list[tuple[int, str]]) -> list[dict]:
    """构造摘要列表。"""
    return [{"chunk_index": idx, "summary": s, "timestamp": 0.0} for idx, s in items]


def _build_diverse_summaries() -> list[dict]:
    """构造能产生多个 T_main 卷边界的摘要列表。

    chunk 6-8 ("妖兽袭击城市...") 相邻 Jaccard 相似度约 0.47，
    介于自定义阈值 0.40 与默认阈值 0.55 之间，因此:
    - 默认阈值 0.55: sim < 0.55 → 触发边界 → 3 个独立卷
    - 自定义阈值 0.40: sim >= 0.40 → 不触发边界 → 合并为 1 个卷
    """
    return _make_summaries([
        (0, "莫凡参加觉醒仪式，觉醒雷系和光系魔法"),
        (1, "莫凡在觉醒仪式上展现双系天赋"),
        (2, "觉醒仪式结束，莫凡回到家中"),
        (3, "张小候在学院学习魔法理论"),
        (4, "张小候在学院修炼魔法"),
        (5, "张小候在学院参加考试"),
        (6, "妖兽袭击城市，英雄集结"),
        (7, "妖兽袭击城市，战斗激烈"),
        (8, "妖兽袭击城市，决战来临"),
        (9, "大战结束，城市重建"),
        (10, "大战结束，英雄凯旋"),
        (11, "大战结束，尾声来临"),
    ])


# ─── T-B1.1: 阈值参数化 ─────────────────────────────────

class TestClusterThresholds:
    """验证 cluster_summaries() 的 thresholds 参数行为。"""

    def test_thresholds_none_uses_defaults(self):
        """thresholds=None 时行为与 v0.5.0 默认行为完全一致。"""
        summaries = _build_diverse_summaries()

        # 不传 thresholds 参数（等价于 v0.5.0 行为）
        result_default = cluster_summaries(summaries, use_embedding=False)
        # 显式传 thresholds=None
        result_none = cluster_summaries(summaries, use_embedding=False, thresholds=None)

        # 两者应完全一致
        assert result_none["t_main_candidates"] == result_default["t_main_candidates"]
        assert result_none["module_candidates"] == result_default["module_candidates"]
        assert result_none["clusters"] == result_default["clusters"]

        # 进一步验证: thresholds=None 与显式传入模块常量也应完全一致
        result_explicit = cluster_summaries(
            summaries,
            use_embedding=False,
            thresholds={
                "temporal": T_MAIN_BOUNDARY_THRESHOLD,
                "scene": SCENE_CLUSTER_THRESHOLD,
                "entity": ENTITY_CLUSTER_THRESHOLD,
            },
        )
        assert result_explicit["t_main_candidates"] == result_default["t_main_candidates"]
        assert result_explicit["module_candidates"] == result_default["module_candidates"]

    def test_thresholds_custom(self):
        """自定义阈值产生与默认不同的聚类结果。

        边界判定为 `sim < threshold`，因此更低阈值意味着更难触发边界，
        产生更少(但更大)的 T_main 卷候选。测试数据中 chunk 6-8 相邻相似度
        约 0.47，介于 0.40 和 0.55 之间，故:
        - 默认 0.55: 触发边界 → 更多卷
        - 自定义 0.40: 不触发 → 更少卷
        """
        summaries = _build_diverse_summaries()

        result_default = cluster_summaries(summaries, use_embedding=False)
        result_custom = cluster_summaries(
            summaries,
            use_embedding=False,
            thresholds={"temporal": 0.40, "scene": 0.55, "entity": 0.50},
        )

        n_default = len(result_default["t_main_candidates"])
        n_custom = len(result_custom["t_main_candidates"])

        # 默认阈值应产生至少 2 个 T_main 卷（构造数据保证）
        assert n_default >= 2, f"默认阈值应产生多个 T_main 卷，实际: {n_default}"

        # 更低阈值 → 更少边界 → 更少(或相等)的 T_main 卷候选
        assert n_custom <= n_default, (
            f"更低阈值应产生更少(或相等)的 T_main 卷候选: "
            f"默认={n_default}, 自定义={n_custom}"
        )

        # 必须产生不同结果以证明参数生效
        assert n_custom != n_default or \
               result_custom["t_main_candidates"] != result_default["t_main_candidates"], (
            "自定义阈值应产生与默认不同的聚类结果"
        )

    def test_thresholds_partial(self):
        """部分覆盖: thresholds={"temporal": 0.40} 仅覆盖 temporal，
        scene/entity 应使用模块默认常量。
        """
        summaries = _build_diverse_summaries()

        # 仅覆盖 temporal
        result_partial = cluster_summaries(
            summaries,
            use_embedding=False,
            thresholds={"temporal": 0.40},
        )

        # 显式传入全部阈值（temporal 自定义 + scene/entity 默认值）
        result_full_explicit = cluster_summaries(
            summaries,
            use_embedding=False,
            thresholds={
                "temporal": 0.40,
                "scene": SCENE_CLUSTER_THRESHOLD,
                "entity": ENTITY_CLUSTER_THRESHOLD,
            },
        )

        # 两者应完全一致（证明部分覆盖时 scene/entity 确实使用默认值）
        assert result_partial["t_main_candidates"] == result_full_explicit["t_main_candidates"], (
            "部分覆盖 temporal 时，t_main_candidates 应与显式传入默认 scene/entity 一致"
        )
        assert result_partial["module_candidates"] == result_full_explicit["module_candidates"], (
            "部分覆盖 temporal 时，module_candidates 应与显式传入默认 scene/entity 一致"
        )

        # 进一步验证: 仅覆盖 temporal 的结果应与默认结果在 t_main 维度不同
        # （因为 temporal 阈值从 0.55 降到 0.40）
        result_default = cluster_summaries(summaries, use_embedding=False)
        n_partial = len(result_partial["t_main_candidates"])
        n_default = len(result_default["t_main_candidates"])

        # temporal 阈值降低 → T_main 卷数应更少或相等
        assert n_partial <= n_default, (
            f"仅降低 temporal 阈值应产生更少(或相等)的 T_main 卷: "
            f"默认={n_default}, 部分覆盖={n_partial}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
