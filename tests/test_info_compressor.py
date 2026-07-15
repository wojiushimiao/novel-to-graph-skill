#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-C2 info_compressor.py v0.4.0 测试

锚定: track_C_plan.md §T-C2
      L3_接口契约与约束.md §1.1.4
检查点: CP-C2.1 (info_compressor 触发压缩) + CP-C2.2 (压缩后字数 ∈ [1200, 1500])

字数统计规则: 按字符数统计 (len(text))，含标点、空格。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pytest

# novel-analysis-skill 目录名含连字符，无法作为 Python 包；
# 同时 pytest 的 pythonpath 配置 (06_核心代码) 存在冲突的 tools 包，
# 需清理 sys.modules 中 tools 相关缓存，并强制把 SKILL_DIR 放到
# sys.path 最前面，确保 tools 解析到本技能的 tools 目录。
for _mod in list(sys.modules):
    if _mod == "tools" or _mod.startswith("tools."):
        del sys.modules[_mod]

_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) in sys.path:
    sys.path.remove(str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from tools.info_compressor import (  # noqa: E402
    compress_info,
    compress_info_with_retry,
    get_compress_prompt,
    get_retry_prompt,
    truncate_info,
    validate_compressed_info,
    InfoTooShortError,
)
from tools.models import (  # noqa: E402
    InfoCompressionError,
    NovelAnalysisError,
)


# ─── 辅助函数 ───────────────────────────────────────────────

def _make_text(length: int) -> str:
    """生成长度为 length 的文本（用中文字符填充，确保 len 精确）。"""
    return "字" * length


def _make_compress_fn(results: list[str]) -> Callable[[str], str]:
    """创建 mock 压缩回调，按顺序返回 results 中的文本。

    模拟宿主 AGENT 调用 LLM：每次调用返回 results 的下一个元素。
    """
    iterator = iter(results)

    def _fn(prompt: str) -> str:
        return next(iterator)

    return _fn


# ─── CP-C2.1: info_compressor 触发压缩 ─────────────────────

class TestCompressInfoTrigger:
    """验证 compress_info 触发逻辑：info > 1500 字返回提示词，否则抛 ValueError。"""

    def test_short_info_raises_value_error(self):
        """info 字数 < 1500 时抛 ValueError（无需压缩）。"""
        info = _make_text(1000)
        with pytest.raises(ValueError, match="无需压缩"):
            compress_info(info)

    def test_boundary_info_raises_value_error(self):
        """info 字数 == 1500（边界）时抛 ValueError。"""
        info = _make_text(1500)
        with pytest.raises(ValueError):
            compress_info(info)

    def test_long_info_returns_prompt(self):
        """info 字数 > 1500 时返回压缩提示词模板。"""
        info = _make_text(2000)
        result = compress_info(info)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_prompt_contains_target_range(self):
        """提示词模板包含目标字数范围。"""
        info = _make_text(2000)
        prompt = compress_info(info, target_min=1200, target_max=1500)
        assert "1200" in prompt
        assert "1500" in prompt

    def test_prompt_contains_original_info(self):
        """提示词模板包含原始 info 文本。"""
        info = "这是原始信息内容" + "字" * 2000
        prompt = compress_info(info)
        assert info in prompt

    def test_custom_target_range(self):
        """自定义 target_min/target_max 生效。"""
        info = _make_text(2000)
        prompt = compress_info(info, target_min=800, target_max=1000)
        assert "800" in prompt
        assert "1000" in prompt


# ─── CP-C2.2: 校验函数 validate_compressed_info ───────────

class TestValidateCompressedInfo:
    """验证字数范围校验：[target_min, target_max] 通过，否则失败。"""

    def test_in_range_pass(self):
        """字数 ∈ [1200, 1500] 通过。"""
        ok, action = validate_compressed_info(_make_text(1300))
        assert ok is True
        assert action == "pass"

    def test_too_short_fails(self):
        """字数 < 1200 失败。"""
        ok, action = validate_compressed_info(_make_text(800))
        assert ok is False
        assert action == "too_short"

    def test_too_long_fails(self):
        """字数 > 1500 失败。"""
        ok, action = validate_compressed_info(_make_text(2000))
        assert ok is False
        assert action == "too_long"

    def test_boundary_min_pass(self):
        """字数 == 1200（下界）通过。"""
        ok, action = validate_compressed_info(_make_text(1200))
        assert ok is True

    def test_boundary_max_pass(self):
        """字数 == 1500（上界）通过。"""
        ok, action = validate_compressed_info(_make_text(1500))
        assert ok is True

    def test_custom_range(self):
        """自定义范围校验。"""
        ok, action = validate_compressed_info(
            _make_text(900), target_min=800, target_max=1000
        )
        assert ok is True


# ─── 截断兜底 truncate_info ────────────────────────────────

class TestTruncateInfo:
    """验证截断兜底：超长文本截断到 target_max。"""

    def test_truncate_to_target_max(self):
        """超长文本截断到 target_max 字。"""
        info = _make_text(2000)
        result = truncate_info(info, target_max=1500)
        assert len(result) == 1500

    def test_truncate_short_unchanged(self):
        """短文本截断后不变。"""
        info = _make_text(1000)
        result = truncate_info(info, target_max=1500)
        assert len(result) == 1000
        assert result == info

    def test_truncate_custom_max(self):
        """自定义 target_max 截断。"""
        info = _make_text(2000)
        result = truncate_info(info, target_max=1000)
        assert len(result) == 1000


# ─── 重试提示词 get_retry_prompt ───────────────────────────

class TestGetRetryPrompt:
    """验证重试提示词包含上下文信息。"""

    def test_retry_prompt_contains_context(self):
        """重试提示词包含原文和压缩结果信息。"""
        original = _make_text(2000)
        compressed = _make_text(1800)
        prompt = get_retry_prompt(original, compressed, 1200, 1500)
        assert original in prompt
        assert "1200" in prompt
        assert "1500" in prompt


# ─── 编排函数 compress_info_with_retry（验收 3/4/5）────────

class TestCompressInfoWithRetry:
    """验证完整压缩流程：触发→校验→重试→截断兜底。"""

    def test_normal_compress(self):
        """正常压缩：mock LLM 返回达标字数，直接通过。"""
        info = _make_text(2000)
        compressed_text = _make_text(1300)
        fn = _make_compress_fn([compressed_text])
        result = compress_info_with_retry(info, fn)
        assert len(result) == 1300
        assert result == compressed_text

    def test_retry_then_pass(self):
        """超长重试：第一次 >1500，第二次达标，重试后通过。"""
        info = _make_text(2000)
        first = _make_text(1800)   # 过长
        second = _make_text(1400)  # 达标
        fn = _make_compress_fn([first, second])
        result = compress_info_with_retry(info, fn)
        assert 1200 <= len(result) <= 1500
        assert result == second

    def test_truncate_fallback(self):
        """截断兜底：重试 2 次仍超限，截断到 target_max。"""
        info = _make_text(2000)
        first = _make_text(1800)   # 过长
        second = _make_text(1900)  # 过长
        third = _make_text(2000)   # 过长
        fn = _make_compress_fn([first, second, third])
        result = compress_info_with_retry(info, fn, max_retries=2)
        assert len(result) == 1500

    def test_too_short_raises(self):
        """压缩后字数 < 1200 触发 InfoTooShortError。"""
        info = _make_text(2000)
        short_text = _make_text(800)  # 过短
        fn = _make_compress_fn([short_text])
        with pytest.raises(InfoTooShortError):
            compress_info_with_retry(info, fn)

    def test_too_short_on_retry_raises(self):
        """重试过程中压缩过度也触发 InfoTooShortError。"""
        info = _make_text(2000)
        first = _make_text(1800)  # 过长，触发重试
        second = _make_text(500)  # 重试后过短
        fn = _make_compress_fn([first, second])
        with pytest.raises(InfoTooShortError):
            compress_info_with_retry(info, fn)

    def test_short_input_raises_value_error(self):
        """输入 info ≤ 1500 抛 ValueError。"""
        info = _make_text(1000)
        fn = _make_compress_fn([])
        with pytest.raises(ValueError, match="无需压缩"):
            compress_info_with_retry(info, fn)

    def test_boundary_input_raises_value_error(self):
        """输入 info == 1500（边界）抛 ValueError。"""
        info = _make_text(1500)
        fn = _make_compress_fn([])
        with pytest.raises(ValueError):
            compress_info_with_retry(info, fn)

    def test_custom_max_retries(self):
        """自定义 max_retries 生效。"""
        info = _make_text(2000)
        # 每次都过长，max_retries=1 → 截断兜底
        fn = _make_compress_fn([_make_text(1800), _make_text(1900)])
        result = compress_info_with_retry(info, fn, max_retries=1)
        assert len(result) == 1500


# ─── 异常层级 ─────────────────────────────────────────────

class TestExceptionHierarchy:
    """验证异常继承关系。"""

    def test_info_too_short_is_info_compression_error(self):
        """InfoTooShortError 是 InfoCompressionError 子类。"""
        assert issubclass(InfoTooShortError, InfoCompressionError)

    def test_info_compression_error_is_novel_analysis_error(self):
        """InfoCompressionError 是 NovelAnalysisError 子类。"""
        assert issubclass(InfoCompressionError, NovelAnalysisError)

    def test_info_too_short_raised_correctly(self):
        """InfoTooShortError 可被 except InfoCompressionError 捕获。"""
        info = _make_text(2000)
        fn = _make_compress_fn([_make_text(500)])
        with pytest.raises(InfoCompressionError):
            compress_info_with_retry(info, fn)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
