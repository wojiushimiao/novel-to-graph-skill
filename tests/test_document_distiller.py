#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-D1 document_distiller.py 测试

锚定: v0.4.1_plan_final.md §T-D1
检查点: CP-D1.1 (Blueprint 四字段完整) / CP-D1.2 (语义块字数 150-400) / CP-D1.3 (降级开关生效)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from document_distiller import distill_chunk, _parse_blueprint  # noqa: E402


# ─── CP-D1.1: Blueprint 四字段完整 ──────────────────────

class TestBlueprintComplete:
    """验证 Blueprint 四字段（场景/行动/变动/因果）完整输出。"""

    def test_four_fields_complete(self):
        """LLM 返回完整 Blueprint，四字段均有内容。"""
        def llm_client(prompt: str) -> str:
            return (
                "场景：博城魔法高中中央广场 觉醒仪式上午 全体新生\n"
                "行动：莫凡上台触碰觉醒石，觉醒雷系和光系魔法\n"
                "变动：莫凡从普通新生跃升为双系法师，能力轨迹改变\n"
                "因果：觉醒石感应 → 双系觉醒 → 全场震惊 → 校方特殊培养"
            )

        chunk_text = "莫凡走上台，触碰觉醒石..."
        result = distill_chunk(chunk_text, llm_client, chunk_index=5)

        assert "scene" in result
        assert "action" in result
        assert "change" in result
        assert "causality" in result
        assert "博城" in result["scene"]
        assert "觉醒" in result["action"]

    def test_raw_summary_generated(self):
        """distill 输出含 raw_summary 字段。"""
        def llm_client(prompt: str) -> str:
            return (
                "场景：博城\n行动：觉醒\n变动：双系\n因果：觉醒石感应"
            )

        result = distill_chunk("原文", llm_client, chunk_index=0)
        assert "raw_summary" in result
        assert isinstance(result["raw_summary"], str)


# ─── CP-D1.2: 语义块字数 150-400 ───────────────────────

class TestWordCount:
    """验证 distill 输出语义块字数在 150-400 范围。"""

    def test_normal_range_word_count(self):
        """正常 distill 输出字数在 150-400 范围内。"""
        def llm_client(prompt: str) -> str:
            # 构造一个 200 字左右的 Blueprint
            return (
                f"场景：{'博城魔法高中中央广场举行觉醒仪式' * 5}\n"
                f"行动：{'莫凡上台触碰觉醒石觉醒雷系和光系' * 5}\n"
                f"变动：{'莫凡从普通新生跃升为双系法师' * 5}\n"
                f"因果：{'觉醒石感应导致双系觉醒引发全场震惊' * 5}"
            )

        result = distill_chunk("原文", llm_client, chunk_index=0)
        total = len(result["scene"] + result["action"] + result["change"] + result["causality"])
        # Blueprint 总字数应在 150-400 范围内（CP-D1.2）
        assert 150 <= total <= 400


# ─── CP-D1.3: 降级开关生效 ─────────────────────────────

class TestSkipSwitch:
    """验证 NOVEL_ANALYSIS_SKIP_DISTILL 降级开关。"""

    def test_skip_distill_returns_raw_chunk(self):
        """环境变量 NOVEL_ANALYSIS_SKIP_DISTILL=1 时跳过 distill，返回原始 chunk。"""
        os.environ["NOVEL_ANALYSIS_SKIP_DISTILL"] = "1"
        try:
            call_count = 0
            def llm_client(prompt: str) -> str:
                nonlocal call_count
                call_count += 1
                return "should_not_be_called"

            chunk_text = "原始 chunk 文本内容"
            result = distill_chunk(chunk_text, llm_client, chunk_index=0)

            assert call_count == 0
            assert result["scene"] == ""
            assert result["action"] == ""
            assert result["change"] == ""
            assert result["causality"] == ""
            assert result["raw_summary"] == chunk_text
            assert result.get("skipped") is True
        finally:
            del os.environ["NOVEL_ANALYSIS_SKIP_DISTILL"]

    def test_no_skip_normal_execution(self):
        """无环境变量时正常执行 distill。"""
        # 确保环境变量不存在
        os.environ.pop("NOVEL_ANALYSIS_SKIP_DISTILL", None)

        def llm_client(prompt: str) -> str:
            return "场景：A\n行动：B\n变动：C\n因果：D"

        result = distill_chunk("原文", llm_client, chunk_index=0)
        assert result.get("skipped") is not True
        assert result["scene"] == "A"


# ─── Blueprint 解析测试 ────────────────────────────────

class TestBlueprintParse:
    """验证 _parse_blueprint 函数。"""

    def test_parse_well_formed_blueprint(self):
        """解析格式正确的 Blueprint。"""
        text = (
            "场景：博城魔法高中\n"
            "行动：莫凡觉醒\n"
            "变动：双系觉醒\n"
            "因果：觉醒石感应"
        )
        result = _parse_blueprint(text)
        assert result["scene"] == "博城魔法高中"
        assert result["action"] == "莫凡觉醒"
        assert result["change"] == "双系觉醒"
        assert result["causality"] == "觉醒石感应"

    def test_parse_missing_field(self):
        """缺失某字段的 Blueprint，对应字段为空字符串。"""
        text = "场景：博城\n行动：觉醒"
        result = _parse_blueprint(text)
        assert result["scene"] == "博城"
        assert result["action"] == "觉醒"
        assert result["change"] == ""
        assert result["causality"] == ""

    def test_parse_empty_text(self):
        """空文本返回全空字段。"""
        result = _parse_blueprint("")
        assert result["scene"] == ""
        assert result["action"] == ""
        assert result["change"] == ""
        assert result["causality"] == ""


# ─── LLM 异常处理测试 ──────────────────────────────────

class TestLlmExceptionHandling:
    """验证 LLM 调用异常时的降级处理（I11 修复）。"""

    def test_llm_exception_returns_raw_chunk(self):
        """LLM 调用异常时返回原始 chunk 文本作为 raw_summary。"""
        def llm_client(prompt: str) -> str:
            raise RuntimeError("API unavailable")

        chunk_text = "原始 chunk 文本内容，用于测试异常降级"
        result = distill_chunk(chunk_text, llm_client, chunk_index=0)

        # 异常时四字段为空
        assert result["scene"] == ""
        assert result["action"] == ""
        assert result["change"] == ""
        assert result["causality"] == ""
        # raw_summary 应为原始 chunk 文本
        assert result["raw_summary"] == chunk_text
        # 不是 skip 模式
        assert result.get("skipped") is not True
        # 应包含 error 字段
        assert "error" in result
