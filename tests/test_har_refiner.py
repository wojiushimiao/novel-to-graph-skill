#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B1 har_refiner.py 测试

锚定: v0.4.1_plan_final.md §T-B1
检查点: CP-B1.1 (重抽3次后达标率>80%) / CP-B1.2 (HAR_FAILED 写入 hint_tags) / CP-B1.3 (预算上限触发中止)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from har_refiner import refine_info  # noqa: E402


# ─── 辅助：构造 LLM client mock ─────────────────────────

def _make_good_info() -> str:
    """构造一个达标的 info（含四段 + src 标记，>500 字）。"""
    return (
        "【起因】" + "起因内容详细描述" * 25 + "[src:chunk_001]\n"
        "【经过】" + "经过内容详细描述" * 40 + "[src:chunk_002]\n"
        "【结果】" + "结果内容详细描述" * 25 + "[src:chunk_003]\n"
        "【模块定位】" + "模块定位详细描述" * 25 + "[src:chunk_004]"
    )


def _make_short_info() -> str:
    """构造一个不达标的 info（< 500 字）。"""
    return "【起因】短[src:chunk_001]\n【经过】短[src:chunk_002]"


# ─── CP-B1.1: 成功重抽 ─────────────────────────────────

class TestRefineInfoSuccess:
    """验证 HAR 重抽成功场景。"""

    def test_short_info_refined_successfully(self):
        """不达标 info 经重抽后达标，返回修正后条目。"""
        # 模拟 LLM：第一次返回达标 info
        def llm_client(prompt: str) -> str:
            return _make_good_info()

        entries = [{"event_id": "E_001", "delta_update": {"updated_fields": {"info": _make_short_info()}}}]
        chunks = {1: "原文chunk1", 2: "原文chunk2"}

        refined, stats = refine_info(entries, chunks, llm_client)

        assert len(refined) == 1
        assert refined[0]["delta_update"]["updated_fields"]["info"] == _make_good_info()
        assert stats["total"] == 1
        assert stats["success"] == 1
        assert stats["failed"] == 0

    def test_no_short_info_returns_unchanged(self):
        """已达标的 info 不触发重抽。"""
        good_info = _make_good_info()
        entries = [{"event_id": "E_001", "delta_update": {"updated_fields": {"info": good_info}}}]

        call_count = 0
        def llm_client(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "should_not_be_called"

        refined, stats = refine_info(entries, {}, llm_client)
        assert call_count == 0
        assert stats["total"] == 0


# ─── CP-B1.2: HAR_FAILED 写入 hint_tags ─────────────────

class TestHarFailedMarking:
    """验证 3 次重抽失败后写入 HAR_FAILED 标记并降级。"""

    def test_three_failures_write_har_failed(self):
        """3 次重抽均失败 → hint_tags 含 HAR_FAILED，importance 降级 low。"""
        def llm_client(prompt: str) -> str:
            # 始终返回不达标 info
            return _make_short_info()

        entries = [{
            "event_id": "E_001",
            "importance": "high",
            "delta_update": {"updated_fields": {"info": _make_short_info()}}
        }]

        refined, stats = refine_info(entries, {1: "chunk1"}, llm_client, max_retries=3, budget_limit=3)

        assert len(refined) == 1
        entry = refined[0]
        hint_tags = entry["delta_update"]["updated_fields"].get("hint_tags", [])
        assert "HAR_FAILED" in hint_tags
        assert entry["importance"] == "low"
        assert stats["failed"] == 1
        assert stats["retries_avg"] == 3


# ─── CP-B1.3: 预算上限触发中止 ──────────────────────────

class TestBudgetAbort:
    """验证预算上限触发批次中止，剩余条目降级。"""

    def test_budget_limit_triggers_abort(self):
        """LLM 调用次数达到预算上限，批次中止。"""
        call_count = 0
        def llm_client(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return _make_short_info()  # 始终失败

        # 5 个条目，预算 = 3 次调用
        entries = [
            {"event_id": f"E_{i:03d}", "importance": "medium",
             "delta_update": {"updated_fields": {"info": _make_short_info()}}}
            for i in range(5)
        ]

        refined, stats = refine_info(entries, {1: "chunk1"}, llm_client,
                                      max_retries=3, budget_limit=3)

        assert stats["aborted"] is True
        assert call_count <= 3
        # 中止后剩余条目应降级为 low
        for entry in refined[1:]:  # 至少从第 2 个开始应为 low
            assert entry["importance"] == "low"

    def test_failure_rate_threshold_triggers_abort(self):
        """单批失败率 >30% 触发中止阈值。"""
        # 让前 4 个失败，第 5 个成功，但失败率 80% > 30% 应触发
        call_idx = 0
        def llm_client(prompt: str) -> str:
            nonlocal call_idx
            call_idx += 1
            if call_idx == 5:
                return _make_good_info()
            return _make_short_info()

        entries = [
            {"event_id": f"E_{i:03d}", "importance": "medium",
             "delta_update": {"updated_fields": {"info": _make_short_info()}}}
            for i in range(5)
        ]

        refined, stats = refine_info(entries, {1: "chunk1"}, llm_client,
                                      max_retries=1, failure_threshold=0.3)

        assert stats["aborted"] is True


# ─── CP-B1.4: LLM 异常不重试 ──────────────────────────────

class TestLlmExceptionHandling:
    """验证 LLM 调用异常时立即标记失败，不重试浪费预算。"""

    def test_llm_exception_counts_as_failure(self):
        """LLM 调用异常时条目标记为失败，不重试。"""
        call_count = 0
        def llm_client(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("API unavailable")

        entries = [{
            "event_id": "E_001",
            "importance": "high",
            "delta_update": {"updated_fields": {"info": _make_short_info()}}
        }]

        refined, stats = refine_info(entries, {1: "chunk1"}, llm_client, max_retries=3)

        assert stats["failed"] == 1
        assert stats["success"] == 0
        assert call_count == 1  # 不应重试
        assert stats["budget_used"] == 1
        assert "HAR_FAILED" in refined[0]["delta_update"]["updated_fields"].get("hint_tags", [])
        assert refined[0]["importance"] == "low"
