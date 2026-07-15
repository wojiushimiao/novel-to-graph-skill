#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-C2 semantic_clusterer.py 测试

锚定: v0.4.1_plan_final.md §T-C2
检查点: CP-C2.1 (时序聚类识别阶段边界) / CP-C2.2 (场景聚类识别地点转移) / CP-C2.3 (降级关键词模式)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from semantic_clusterer import cluster_summaries, _jaccard_similarity  # noqa: E402
import semantic_clusterer as _sc  # noqa: E402


# ─── 测试数据构造 ───────────────────────────────────────

def _make_summaries(items: list[tuple[int, str]]) -> list[dict]:
    """构造摘要列表。"""
    return [{"chunk_index": idx, "summary": s, "timestamp": 0.0} for idx, s in items]


# ─── CP-C2.1: 时序聚类识别阶段边界 ─────────────────────

class TestTemporalCluster:
    """验证时序聚类能识别阶段边界（T_main 卷候选）。"""

    def test_clear_boundary_detected(self):
        """明显主题切换时识别 T_main 卷边界。"""
        summaries = _make_summaries([
            (0, "莫凡参加觉醒仪式，觉醒雷系和光系魔法"),
            (1, "莫凡在觉醒仪式上展现双系天赋，全场震惊"),
            (2, "觉醒仪式结束，莫凡回到家中休息"),
            (3, "莫凡进入魔法学院学习，开始系统修炼"),
            (4, "魔法学院的课程安排紧凑，莫凡适应新环境"),
            (5, "莫凡在学院结识张小候，两人成为挚友"),
        ])
        result = cluster_summaries(summaries, use_embedding=False)

        assert "t_main_candidates" in result
        assert len(result["t_main_candidates"]) >= 1
        # 应在 chunk 2-3 之间检测到边界（觉醒仪式 → 学院生活）
        t_main = result["t_main_candidates"][0]
        assert "range" in t_main or "start_chunk" in t_main

    def test_no_boundary_single_theme(self):
        """单一主题无明显边界，返回 1 个 T_main 卷。"""
        summaries = _make_summaries([
            (i, f"莫凡在学院学习魔法理论第{i}天") for i in range(8)
        ])
        result = cluster_summaries(summaries, use_embedding=False)
        assert len(result["t_main_candidates"]) == 1


# ─── CP-C2.2: 场景聚类识别地点转移 ─────────────────────

class TestSceneCluster:
    """验证场景聚类能识别地点转移（E_module 边界辅助）。"""

    def test_location_transfer_detected(self):
        """明显地点转移时识别 E_module 边界。"""
        summaries = _make_summaries([
            (0, "博城魔法高中举行觉醒仪式"),
            (1, "博城魔法高中的操场上学生集合"),
            (2, "博城市中心遭遇妖兽袭击"),
            (3, "魔法学院组织学生撤离到安全区"),
            (4, "上海魔法学院迎来新学期"),
            (5, "上海魔法学院的修炼场开放"),
        ])
        result = cluster_summaries(summaries, use_embedding=False)

        assert "module_candidates" in result
        # 应至少识别出 1 个 E_module 候选
        assert len(result["module_candidates"]) >= 1


# ─── CP-C2.3: 降级关键词模式 ──────────────────────────

class TestKeywordFallback:
    """验证降级关键词模式（Jaccard 相似度）。"""

    def test_jaccard_similarity_identical(self):
        """完全相同的关键词集 Jaccard=1.0。"""
        set_a = {"莫凡", "觉醒", "雷系"}
        set_b = {"莫凡", "觉醒", "雷系"}
        assert _jaccard_similarity(set_a, set_b) == 1.0

    def test_jaccard_similarity_disjoint(self):
        """完全不重叠 Jaccard=0.0。"""
        set_a = {"莫凡", "觉醒"}
        set_b = {"张小候", "学院"}
        assert _jaccard_similarity(set_a, set_b) == 0.0

    def test_jaccard_similarity_partial(self):
        """部分重叠 Jaccard ∈ (0, 1)。"""
        set_a = {"莫凡", "觉醒", "雷系"}
        set_b = {"莫凡", "学院", "张小候"}
        # 交集 = {莫凡} = 1，并集 = {莫凡,觉醒,雷系,学院,张小候} = 5
        assert _jaccard_similarity(set_a, set_b) == pytest.approx(0.2)

    def test_fallback_produces_candidates(self):
        """降级模式下能产出候选。"""
        summaries = _make_summaries([
            (0, "莫凡觉醒仪式雷系"),
            (1, "莫凡雷系觉醒"),
            (2, "张小候学院生活"),
            (3, "张小候学院修炼"),
        ])
        result = cluster_summaries(summaries, use_embedding=False)
        assert "t_main_candidates" in result
        assert "module_candidates" in result
        assert isinstance(result["t_main_candidates"], list)


# ─── 边界情况 ──────────────────────────────────────────

class TestEdgeCases:
    """验证边界情况。"""

    def test_empty_summaries(self):
        """空摘要列表返回空结果。"""
        result = cluster_summaries([], use_embedding=False)
        assert result["t_main_candidates"] == []
        assert result["module_candidates"] == []

    def test_single_summary(self):
        """单条摘要返回 1 个 T_main 卷。"""
        summaries = _make_summaries([(0, "莫凡觉醒")])
        result = cluster_summaries(summaries, use_embedding=False)
        assert len(result["t_main_candidates"]) == 1

    def test_stage_distribution_not_all_development(self):
        """多卷时 stage 分布应有多样性，非全部为"发展"。"""
        # 构造足够多的摘要，确保产生多个 T_main 卷
        summaries = _make_summaries([
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
        result = cluster_summaries(summaries, use_embedding=False)
        candidates = result["t_main_candidates"]
        assert len(candidates) >= 2, "构造的数据应产生至少 2 个 T_main 卷"

        stages = [c["stage"] for c in candidates]
        unique_stages = set(stages)
        assert len(unique_stages) >= 2, (
            f"stage 应有多样性，实际全部为: {stages}"
        )


# ─── CP-C2.4: Embedding 模式 ─────────────────────────────

np = pytest.importorskip("numpy", reason="numpy required for embedding tests")

import sys as _sys  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

# 预注册 mock sentence_transformers 模块，使 @patch.object 可正常解析
# （sentence_transformers 未安装时 @patch 无法解析模块路径）
if 'sentence_transformers' not in _sys.modules:
    _sys.modules['sentence_transformers'] = MagicMock()


class TestEmbeddingMode:
    """验证 embedding 模式（use_embedding=True）正常工作。"""

    def setup_method(self):
        """每个测试前清理模型缓存，避免测试间污染。"""
        _sc._EMBEDDING_MODEL_CACHE.clear()

    def teardown_method(self):
        """每个测试后清理模型缓存。"""
        _sc._EMBEDDING_MODEL_CACHE.clear()

    @patch.object(_sys.modules['sentence_transformers'], 'SentenceTransformer')
    def test_embedding_mode_produces_results(self, mock_st):
        """embedding 模式应产出正确的聚类结果结构。"""
        # 正交嵌入向量 → 相邻 chunk 余弦相似度 = 0.0 → 每个 chunk 都是独立 T_main 卷
        fake_embeddings = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)
        mock_model = MagicMock()
        mock_model.encode.return_value = fake_embeddings
        mock_st.return_value = mock_model

        summaries = _make_summaries([
            (0, "莫凡参加觉醒仪式"),
            (1, "张小候在学院修炼"),
            (2, "妖兽袭击城市"),
        ])
        result = cluster_summaries(summaries, use_embedding=True)

        assert "t_main_candidates" in result
        assert "module_candidates" in result
        assert "clusters" in result
        # 正交嵌入 → 相邻 sim=0.0 < 0.55 → 3 个独立 T_main 卷
        assert len(result["t_main_candidates"]) == 3

    @patch.object(_sys.modules['sentence_transformers'], 'SentenceTransformer')
    def test_embedding_mode_different_from_keyword(self, mock_st):
        """embedding 模式与关键词模式产生不同聚类结果。"""
        # 高度相似的嵌入向量 → 所有 chunk 间 cosine ≈ 1.0 → 1 个 T_main 卷
        fake_embeddings = np.array([
            [1.0, 0.1, 0.0],
            [1.0, 0.0, 0.1],
            [1.0, 0.1, 0.1],
        ], dtype=np.float64)
        mock_model = MagicMock()
        mock_model.encode.return_value = fake_embeddings
        mock_st.return_value = mock_model

        summaries = _make_summaries([
            (0, "莫凡参加觉醒仪式，觉醒雷系和光系魔法"),
            (1, "莫凡在觉醒仪式上展现双系天赋"),
            (2, "觉醒仪式结束，莫凡回到家中"),
        ])
        result_embedding = cluster_summaries(summaries, use_embedding=True)
        result_keyword = cluster_summaries(summaries, use_embedding=False)

        # 嵌入模式产生 1 个 T_main 卷（高相似度）
        assert len(result_embedding["t_main_candidates"]) == 1
        # 关键词模式应产生不同数量的 T_main 卷
        assert len(result_embedding["t_main_candidates"]) != len(
            result_keyword["t_main_candidates"]
        ), "embedding 模式与 keyword 模式应产生不同数量的 T_main 卷"


class TestEmbeddingDegradation:
    """验证 embedding 不可用时的降级路径。"""

    def setup_method(self):
        """每个测试前清理模型缓存。"""
        _sc._EMBEDDING_MODEL_CACHE.clear()

    def teardown_method(self):
        """每个测试后清理模型缓存。"""
        _sc._EMBEDDING_MODEL_CACHE.clear()

    @patch.object(_sys.modules['sentence_transformers'], 'SentenceTransformer')
    def test_import_error_falls_back_to_keyword(self, mock_st):
        """sentence_transformers 导入失败时降级为关键词模式，不崩溃。"""
        mock_st.side_effect = ImportError("No module named 'sentence_transformers'")

        summaries = _make_summaries([
            (0, "莫凡参加觉醒仪式"),
            (1, "莫凡在觉醒仪式上展现双系天赋"),
            (2, "觉醒仪式结束"),
        ])
        result = cluster_summaries(summaries, use_embedding=True)

        assert "t_main_candidates" in result
        assert len(result["t_main_candidates"]) >= 1

        # 降级结果应与直接使用 keyword 模式一致
        result_direct = cluster_summaries(summaries, use_embedding=False)
        assert result["t_main_candidates"] == result_direct["t_main_candidates"]
        assert result["module_candidates"] == result_direct["module_candidates"]

    @patch.object(_sys.modules['sentence_transformers'], 'SentenceTransformer')
    def test_model_error_falls_back_gracefully(self, mock_st):
        """模型推理失败时降级不崩溃。"""
        mock_model = MagicMock()
        mock_model.encode.side_effect = RuntimeError("CUDA out of memory")
        mock_st.return_value = mock_model

        summaries = _make_summaries([
            (0, "莫凡参加觉醒仪式"),
            (1, "莫凡在觉醒仪式上展现双系天赋"),
        ])
        result = cluster_summaries(summaries, use_embedding=True)

        assert "t_main_candidates" in result
        assert len(result["t_main_candidates"]) >= 1
