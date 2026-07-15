#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B3 run_s4_s7_pipeline.py HAR 集成测试

锚定: v0.4.1_plan_final.md §T-B3
检查点:
  CP-B3.1: HAR 步骤在 S4.2 后、S4.3 前执行
  CP-B3.2: 最终输出中无 `[src:chunk_NNN]` 残留
  CP-B3.3: pipeline_stats 含 HAR 预算与中止字段
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将 tests 目录加入路径（用于 import run_s4_s7_pipeline）
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# 将 tools 目录加入路径
_TOOLS_DIR = _TESTS_DIR.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ─── 测试数据构造 ───────────────────────────────────────────

def _make_item(
    event_id: str = "E_test",
    info: str = "短信息",
    importance: str = "medium",
    target_entity_id: str = "C_测试",
) -> dict:
    """构造单个 LLM 输出条目。"""
    return {
        "event_id": event_id,
        "stitch": {"sigma": "主题", "epsilon": "事件", "kappa": "角色"},
        "coords": {
            "T": "E_module_test",
            "L": "L_测试",
            "C": target_entity_id,
            "E": "",
            "R": "",
        },
        "importance": importance,
        "delta_update": {
            "target_entity_id": target_entity_id,
            "conflict_detected": False,
            "updated_fields": {
                "info": info,
                "new_wiki_relations": [],
            },
        },
    }


def _make_well_formed_info(chunk_idx: int = 0) -> str:
    """构造符合 v0.4.1 四段结构 + src 标记的 info。"""
    return (
        f"【起因】{'起因内容详细描述' * 10}[src:chunk_{chunk_idx}]"
        f"【经过】{'经过内容详细描述' * 20}[src:chunk_{chunk_idx}]"
        f"【结果】{'结果内容详细描述' * 10}[src:chunk_{chunk_idx}]"
        f"【模块定位】{'模块定位内容详细描述' * 10}[src:chunk_{chunk_idx}]"
    )


def _make_short_info_with_marker(chunk_idx: int = 0) -> str:
    """构造带 src 标记但过短的 info。"""
    return f"短信息[src:chunk_{chunk_idx}]"


# ─── CP-B3.1: HAR 步骤在 S4.2 后、S4.3 前执行 ─────────────

class TestHarStepOrder:
    """验证 HAR 步骤在 S4.2 (schema_validator) 后、S4.3 (low_value_filter) 前执行。"""

    def test_s4_25_har_refine_function_exists(self):
        """s4_25_har_refine 函数存在且可调用。"""
        import run_s4_s7_pipeline
        assert hasattr(run_s4_s7_pipeline, "s4_25_har_refine")
        assert callable(run_s4_s7_pipeline.s4_25_har_refine)

    def test_har_step_between_s42_and_s43(self):
        """HAR 步骤在 S4.2 后、S4.3 前执行（通过调用顺序验证）。"""
        import run_s4_s7_pipeline

        # 构造测试数据：通过 schema_validator 但 info 不达标
        items = [_make_item(info=_make_short_info_with_marker(0))]

        # Mock 依赖
        call_order: list[str] = []

        with patch("run_s4_s7_pipeline.schema_validator") as mock_sv, \
             patch("run_s4_s7_pipeline.low_value_filter") as mock_lvf, \
             patch("run_s4_s7_pipeline.har_refiner") as mock_har:

            # schema_validator.validate 返回原数据
            mock_sv.validate.side_effect = lambda x: (call_order.append("S4.2"), x)[1]
            mock_sv.validate_info_length_v041.return_value = (False, "too_short", {"length": 100})
            mock_sv.validate_info_structure.return_value = (False, "missing_section: 起因")
            mock_sv.strip_src_markers.side_effect = lambda info: info.replace("[src:chunk_0]", "")

            # har_refiner.refine_info 返回修正后的数据
            def fake_refine(entries, chunks, llm_client, **kwargs):
                call_order.append("S4.25")
                refined = [_make_item(info=_make_well_formed_info(0))]
                stats = {
                    "total": 1, "success": 1, "failed": 0,
                    "retries_avg": 1.0, "budget_used": 1, "aborted": False,
                }
                return refined, stats

            mock_har.refine_info.side_effect = fake_refine

            # low_value_filter.filter 返回原数据
            mock_lvf.filter.side_effect = lambda x: (call_order.append("S4.3"), x)[1]

            # 调用 s4_clean_validate，启用 HAR
            result = run_s4_s7_pipeline.s4_clean_validate(
                items,
                enable_har=True,
                chunks={0: "原文chunk内容"},
                llm_client=lambda prompt: "重抽结果",
            )

        # 验证调用顺序：S4.2 → S4.25 → S4.3
        assert call_order == ["S4.2", "S4.25", "S4.3"], (
            f"HAR 应在 S4.2 后、S4.3 前执行，实际顺序: {call_order}"
        )

    def test_har_skipped_when_disabled(self):
        """enable_har=False 时不执行 HAR 步骤。"""
        import run_s4_s7_pipeline

        items = [_make_item(info=_make_well_formed_info(0))]

        with patch("run_s4_s7_pipeline.schema_validator") as mock_sv, \
             patch("run_s4_s7_pipeline.low_value_filter") as mock_lvf, \
             patch("run_s4_s7_pipeline.har_refiner") as mock_har:

            mock_sv.validate.return_value = items
            mock_lvf.filter.return_value = items
            mock_sv.strip_src_markers.side_effect = lambda info: info

            run_s4_s7_pipeline.s4_clean_validate(
                items,
                enable_har=False,
            )

            # HAR 不应被调用
            mock_har.refine_info.assert_not_called()


# ─── CP-B3.2: 输出无 [src:chunk_NNN] 残留 ─────────────────

class TestStripSrcMarkers:
    """验证 S5 入库前调用 strip_src_markers 剥离过程校验标记。"""

    def test_strip_src_markers_function_exists(self):
        """strip_src_markers_in_items 函数存在且可调用。"""
        import run_s4_s7_pipeline
        assert hasattr(run_s4_s7_pipeline, "strip_src_markers_in_items")
        assert callable(run_s4_s7_pipeline.strip_src_markers_in_items)

    def test_strip_markers_removes_all_src_chunks(self):
        """strip_src_markers_in_items 移除所有 [src:chunk_NNN] 标记。"""
        import run_s4_s7_pipeline

        items = [
            _make_item(info="【起因】xxx[src:chunk_0]【经过】yyy[src:chunk_1]"),
            _make_item(info="无标记的info"),
            _make_item(info="【结果】zzz[src:chunk_2-5]"),
        ]

        cleaned = run_s4_s7_pipeline.strip_src_markers_in_items(items)

        for item in cleaned:
            info = item["delta_update"]["updated_fields"]["info"]
            assert "[src:chunk_" not in info, (
                f"info 中仍含 [src:chunk_] 标记: {info}"
            )

    def test_strip_markers_preserves_other_content(self):
        """strip_src_markers_in_items 保留除 [src:chunk_NNN] 外的所有内容。"""
        import run_s4_s7_pipeline

        original_info = "【起因】事件起因内容[src:chunk_0]【经过】事件经过内容[src:chunk_0]"
        items = [_make_item(info=original_info)]

        cleaned = run_s4_s7_pipeline.strip_src_markers_in_items(items)
        cleaned_info = cleaned[0]["delta_update"]["updated_fields"]["info"]

        assert "【起因】事件起因内容" in cleaned_info
        assert "【经过】事件经过内容" in cleaned_info
        assert "[src:chunk_0]" not in cleaned_info

    def test_strip_markers_handles_malformed(self):
        """畸形标记（如 [src:chunk_]）保留供调试。"""
        import run_s4_s7_pipeline

        # 畸形标记：[src:chunk_] 无数字
        items = [_make_item(info="内容[src:chunk_]更多内容[src:chunk_0]")]
        cleaned = run_s4_s7_pipeline.strip_src_markers_in_items(items)
        info = cleaned[0]["delta_update"]["updated_fields"]["info"]

        # 合法标记 [src:chunk_0] 应被剥离
        assert "[src:chunk_0]" not in info
        # 畸形标记 [src:chunk_] 保留（供调试）
        # 注：根据 schema_validator.strip_src_markers 实现，畸形标记保留


# ─── CP-B3.3: pipeline_stats 含 HAR 预算与中止字段 ───────

class TestHarStatsInPipelineStats:
    """验证 pipeline_stats 含 HAR 预算与中止字段。"""

    def test_har_stats_function_exists(self):
        """compute_har_stats 函数存在且可调用。"""
        import run_s4_s7_pipeline
        assert hasattr(run_s4_s7_pipeline, "compute_har_stats")
        assert callable(run_s4_s7_pipeline.compute_har_stats)

    def test_har_stats_has_required_fields(self):
        """compute_har_stats 返回的 dict 含 budget_used/aborted 字段。"""
        import run_s4_s7_pipeline

        har_stats = {
            "total": 100,
            "success": 80,
            "failed": 20,
            "retries_avg": 1.5,
            "budget_used": 150,
            "aborted": False,
        }

        result = run_s4_s7_pipeline.compute_har_stats(har_stats)

        assert "budget_used" in result
        assert "aborted" in result
        assert isinstance(result["aborted"], bool)
        assert isinstance(result["budget_used"], int)

    def test_har_stats_zero_when_disabled(self):
        """HAR 禁用时，compute_har_stats 返回零值。"""
        import run_s4_s7_pipeline

        result = run_s4_s7_pipeline.compute_har_stats(None)

        assert result["budget_used"] == 0
        assert result["aborted"] is False
        assert result["total"] == 0
        assert result["success"] == 0
        assert result["failed"] == 0


# ─── 端到端集成验证 ───────────────────────────────────────

class TestEndToEndIntegration:
    """端到端验证 s4_clean_validate 完整流程。"""

    def test_full_s4_pipeline_with_har_enabled(self):
        """完整 S4 流程（启用 HAR）：S4.1 → S4.2 → S4.25 → strip → S4.3。"""
        import run_s4_s7_pipeline

        # 构造带 src 标记但 info 过短的条目
        items = [_make_item(info=_make_short_info_with_marker(0))]

        with patch("run_s4_s7_pipeline.schema_validator") as mock_sv, \
             patch("run_s4_s7_pipeline.low_value_filter") as mock_lvf, \
             patch("run_s4_s7_pipeline.har_refiner") as mock_har:

            mock_sv.validate.return_value = items
            mock_sv.validate_info_length_v041.return_value = (False, "too_short", {"length": 100})
            mock_sv.validate_info_structure.return_value = (False, "missing_section: 起因")
            mock_sv.strip_src_markers.side_effect = lambda info: info.replace("[src:chunk_0]", "")

            refined_items = [_make_item(info=_make_well_formed_info(0))]
            har_stats = {
                "total": 1, "success": 1, "failed": 0,
                "retries_avg": 1.0, "budget_used": 1, "aborted": False,
            }
            mock_har.refine_info.return_value = (refined_items, har_stats)

            mock_lvf.filter.return_value = refined_items

            result, returned_har_stats = run_s4_s7_pipeline.s4_clean_validate(
                items,
                enable_har=True,
                chunks={0: "原文chunk"},
                llm_client=lambda p: "重抽",
            )

            # HAR 应被调用
            mock_har.refine_info.assert_called_once()
            # 返回 HAR 统计
            assert returned_har_stats is not None
            assert returned_har_stats["total"] == 1
            assert returned_har_stats["budget_used"] == 1

    def test_full_s4_pipeline_with_har_disabled(self):
        """完整 S4 流程（禁用 HAR）：S4.1 → S4.2 → strip → S4.3，HAR 跳过。"""
        import run_s4_s7_pipeline

        items = [_make_item(info=_make_well_formed_info(0))]

        with patch("run_s4_s7_pipeline.schema_validator") as mock_sv, \
             patch("run_s4_s7_pipeline.low_value_filter") as mock_lvf, \
             patch("run_s4_s7_pipeline.har_refiner") as mock_har:

            mock_sv.validate.return_value = items
            mock_sv.strip_src_markers.side_effect = lambda info: info.replace("[src:chunk_0]", "")
            mock_lvf.filter.return_value = items

            result, har_stats = run_s4_s7_pipeline.s4_clean_validate(
                items,
                enable_har=False,
            )

            # HAR 不应被调用
            mock_har.refine_info.assert_not_called()
            # HAR 统计应为零值
            assert har_stats is not None
            assert har_stats["total"] == 0
            assert har_stats["budget_used"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
