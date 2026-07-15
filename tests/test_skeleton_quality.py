#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 骨架质量评估单元测试（v0.5.1 B1）

锚定: graph_builder.evaluate_skeleton_quality
      timeline_skeleton_builder.Skeleton

覆盖五个场景:
1. 优质骨架 → verdict=pass
2. T_main 卷数过少 → verdict=rebuild
3. E_module 颗粒度过粗 → verdict=rebuild
4. T_branch 覆盖率不足 → verdict=rebuild
5. 空骨架 → verdict=rebuild
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from models import Entity, Relation
from timeline_skeleton_builder import Skeleton
from graph_builder import evaluate_skeleton_quality, SKELETON_QUALITY


# ─── 测试数据构造辅助函数 ─────────────────────────────────

def _make_t_main_volumes(n: int) -> list[Entity]:
    """构造 n 个 T_main 卷实体。"""
    return [
        Entity(id=f"T_main_vol_{i}", name=f"剧情卷_{i + 1}", type="T_main")
        for i in range(n)
    ]


def _make_e_modules(n: int) -> list[Entity]:
    """构造 n 个 E_module 实体。"""
    return [
        Entity(id=f"E_module_{i}", name=f"剧情模块_{i + 1}", type="E_module")
        for i in range(n)
    ]


def _make_t_branch_relations(module_indices: list[int], branches_per_module: int = 3) -> list[Relation]:
    """为指定 E_module 索引列表构造 T_branch 入边关系。

    Args:
        module_indices: 需要挂载 T_branch 的 E_module 索引列表
        branches_per_module: 每个 E_module 挂载的 T_branch 数量

    Returns:
        Relation 列表，每条关系 target_id 指向对应 E_module
    """
    relations: list[Relation] = []
    for idx in module_indices:
        mod_id = f"E_module_{idx}"
        for j in range(branches_per_module):
            relations.append(Relation(
                source_id=f"E_event_{idx}_{j}",
                target_id=mod_id,
                relation_type="T_branch",
            ))
    return relations


# ─── 测试用例 ─────────────────────────────────────────────

class TestEvaluateSkeletonQuality:
    """evaluate_skeleton_quality 五场景覆盖。"""

    def test_quality_pass(self):
        """优质骨架: 10 T_main, 5 模块/卷, 80% 覆盖率 → verdict=pass。"""
        skeleton = Skeleton(
            t_main_volumes=_make_t_main_volumes(10),
            e_modules=_make_e_modules(50),
        )
        # 50 个 E_module 中前 40 个各挂 3 条 T_branch → 覆盖率 40/50=0.8
        relations = _make_t_branch_relations(list(range(40)))

        result = evaluate_skeleton_quality(skeleton, [], relations)

        assert result["verdict"] == "pass"
        assert result["t_main_count"] == 10
        assert result["avg_modules_per_vol"] == pytest.approx(5.0)
        assert result["t_branch_coverage"] == pytest.approx(0.8)
        assert result["issues"] == []

    def test_quality_t_main_too_few(self):
        """T_main 卷数过少: 3 卷 (< 5) → verdict=rebuild。"""
        skeleton = Skeleton(
            t_main_volumes=_make_t_main_volumes(3),
            e_modules=_make_e_modules(12),
        )
        # 12 个 E_module 全部覆盖 → 覆盖率 1.0 (OK)
        # avg = 12/3 = 4.0 (OK, ≥ 2)
        relations = _make_t_branch_relations(list(range(12)))

        result = evaluate_skeleton_quality(skeleton, [], relations)

        assert result["verdict"] == "rebuild"
        assert result["t_main_count"] == 3
        assert "T_main 卷数过少" in result["issues"]
        # 其他维度不应触发
        assert "E_module 颗粒度过粗" not in result["issues"]
        assert "T_branch 覆盖率不足" not in result["issues"]

    def test_quality_modules_too_coarse(self):
        """E_module 颗粒度过粗: 10 卷但仅 10 模块 (1/卷 < 2) → verdict=rebuild。"""
        skeleton = Skeleton(
            t_main_volumes=_make_t_main_volumes(10),
            e_modules=_make_e_modules(10),
        )
        # 10 个 E_module 全部覆盖 → 覆盖率 1.0 (OK)
        relations = _make_t_branch_relations(list(range(10)))

        result = evaluate_skeleton_quality(skeleton, [], relations)

        assert result["verdict"] == "rebuild"
        assert result["avg_modules_per_vol"] == pytest.approx(1.0)
        assert "E_module 颗粒度过粗" in result["issues"]
        # 其他维度不应触发
        assert "T_main 卷数过少" not in result["issues"]
        assert "T_branch 覆盖率不足" not in result["issues"]

    def test_quality_coverage_low(self):
        """T_branch 覆盖率不足: 40 模块仅 12 覆盖 (30% < 60%) → verdict=rebuild。"""
        skeleton = Skeleton(
            t_main_volumes=_make_t_main_volumes(10),
            e_modules=_make_e_modules(40),
        )
        # 40 个 E_module 中仅前 12 个覆盖 → 覆盖率 12/40=0.3
        relations = _make_t_branch_relations(list(range(12)))

        result = evaluate_skeleton_quality(skeleton, [], relations)

        assert result["verdict"] == "rebuild"
        assert result["t_branch_coverage"] == pytest.approx(0.3)
        assert "T_branch 覆盖率不足" in result["issues"]
        # 其他维度不应触发
        assert "T_main 卷数过少" not in result["issues"]
        assert "E_module 颗粒度过粗" not in result["issues"]

    def test_quality_empty_skeleton(self):
        """空骨架: 无 T_main 卷、无 E_module → verdict=rebuild, issues=['骨架为空']。"""
        skeleton = Skeleton()

        result = evaluate_skeleton_quality(skeleton, [], [])

        assert result["verdict"] == "rebuild"
        assert result["t_main_count"] == 0
        assert result["avg_modules_per_vol"] == pytest.approx(0.0)
        assert result["t_branch_coverage"] == pytest.approx(0.0)
        assert result["issues"] == ["骨架为空"]
