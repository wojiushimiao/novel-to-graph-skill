#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B2 schema_validator.py v0.4.1 HAR 接口扩展测试

锚定: v0.4.1_plan_final.md §T-B2
检查点: CP-B2.1 (四段结构3态) / CP-B2.2 (strip_src_markers) / CP-B2.3 (validate_src_marker)

覆盖函数:
- validate_info_structure: 校验四段结构完整性
- validate_src_marker: 校验 [src:chunk_NNN] 标记
- strip_src_markers: 剥离过程校验标记
- validate_info_length_v041: 扩展返回 HAR 元数据
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from schema_validator import (  # noqa: E402
    validate_info_structure,
    validate_src_marker,
    strip_src_markers,
    validate_info_length_v041,
)


# ─── CP-B2.1: validate_info_structure ─────────────────────

class TestValidateInfoStructure:
    """验证 info 四段结构完整性（存在/缺失/空值 三态）。"""

    def test_complete_four_sections_pass(self):
        """四段完整且字数达标，通过。"""
        info = (
            "【起因】" + "起因内容详细描述" * 20 + "[src:chunk_001]\n"
            "【经过】" + "经过内容详细描述" * 30 + "[src:chunk_002]\n"
            "【结果】" + "结果内容详细描述" * 20 + "[src:chunk_003]\n"
            "【模块定位】" + "模块定位详细描述" * 20 + "[src:chunk_004]"
        )
        passed, msg = validate_info_structure(info)
        assert passed is True
        assert msg == "pass"

    def test_missing_section_fails(self):
        """缺失"【结果】"段，返回 missing_section。"""
        info = (
            "【起因】" + "起因内容详细描述" * 20 + "[src:chunk_001]\n"
            "【经过】" + "经过内容详细描述" * 30 + "[src:chunk_002]\n"
            "【模块定位】" + "模块定位详细描述" * 20 + "[src:chunk_004]"
        )
        passed, msg = validate_info_structure(info)
        assert passed is False
        assert "missing_section" in msg
        assert "结果" in msg

    def test_section_too_short_fails(self):
        """段内字数不足，返回 section_too_short。"""
        info = (
            "【起因】短" + "[src:chunk_001]\n"
            "【经过】" + "经过内容" * 30 + "[src:chunk_002]\n"
            "【结果】" + "结果内容" * 20 + "[src:chunk_003]\n"
            "【模块定位】" + "模块定位" * 20 + "[src:chunk_004]"
        )
        passed, msg = validate_info_structure(info)
        assert passed is False
        assert "section_too_short" in msg
        assert "起因" in msg

    def test_empty_info_fails(self):
        """空字符串，返回 missing_section。"""
        passed, msg = validate_info_structure("")
        assert passed is False
        assert "missing_section" in msg


# ─── CP-B2.2: strip_src_markers ─────────────────────────

class TestStripSrcMarkers:
    """验证 [src:chunk_NNN] 标记剥离（单标记/多标记/无标记/畸形标记）。"""

    def test_single_marker_stripped(self):
        """单个标记被剥离。"""
        info = "【起因】内容描述[src:chunk_001]"
        result = strip_src_markers(info)
        assert "[src:" not in result
        assert "内容描述" in result

    def test_multiple_markers_stripped(self):
        """多个标记全部被剥离。"""
        info = (
            "【起因】起因[src:chunk_001]\n"
            "【经过】经过[src:chunk_002-005]\n"
            "【结果】结果[src:chunk_006]"
        )
        result = strip_src_markers(info)
        assert "[src:" not in result
        assert result.count("src") == 0

    def test_no_marker_unchanged(self):
        """无标记的文本不变。"""
        info = "【起因】起因内容\n【经过】经过内容"
        result = strip_src_markers(info)
        assert result == info

    def test_malformed_marker_preserved(self):
        """畸形标记不剥离（保留以供调试）。"""
        info = "内容[src:chunk_abc]"
        result = strip_src_markers(info)
        assert "[src:chunk_abc]" in result


# ─── CP-B2.3: validate_src_marker ────────────────────────

class TestValidateSrcMarker:
    """验证 [src:chunk_NNN] 标记校验（缺失/畸形/合法）。"""

    def test_all_sections_with_markers_pass(self):
        """四段均含合法标记，通过。"""
        info = (
            "【起因】起因内容[src:chunk_001]\n"
            "【经过】经过内容[src:chunk_002]\n"
            "【结果】结果内容[src:chunk_003]\n"
            "【模块定位】模块定位[src:chunk_004]"
        )
        passed, msg = validate_src_marker(info)
        assert passed is True
        assert msg == "pass"

    def test_missing_marker_fails(self):
        """某段缺失标记，返回 missing_marker。"""
        info = (
            "【起因】起因内容[src:chunk_001]\n"
            "【经过】经过内容\n"
            "【结果】结果内容[src:chunk_003]\n"
            "【模块定位】模块定位[src:chunk_004]"
        )
        passed, msg = validate_src_marker(info)
        assert passed is False
        assert "missing_marker" in msg
        assert "经过" in msg

    def test_malformed_marker_fails(self):
        """畸形标记，返回 malformed_marker。"""
        info = (
            "【起因】起因内容[src:chunk_]\n"
            "【经过】经过内容[src:chunk_002]\n"
            "【结果】结果内容[src:chunk_003]\n"
            "【模块定位】模块定位[src:chunk_004]"
        )
        passed, msg = validate_src_marker(info)
        assert passed is False
        assert "malformed" in msg.lower()


# ─── validate_info_length_v041 ──────────────────────────

class TestValidateInfoLengthV041:
    """验证扩展的 info 字数校验（返回 HAR 元数据）。"""

    def test_too_short_returns_metadata(self):
        """字数 <500 返回失败 + HAR 元数据。"""
        info = "a" * 499
        passed, msg, meta = validate_info_length_v041(info)
        assert passed is False
        assert "short" in msg.lower()
        assert "length" in meta
        assert meta["length"] == 499
        assert "needs_har" in meta
        assert meta["needs_har"] is True

    def test_normal_range_passes(self):
        """字数 500-1500 通过。"""
        info = "a" * 800
        passed, msg, meta = validate_info_length_v041(info)
        assert passed is True
        assert msg == "pass"
        assert meta["needs_har"] is False

    def test_too_long_triggers_compress(self):
        """字数 >1500 触发压缩。"""
        info = "a" * 1501
        passed, msg, meta = validate_info_length_v041(info)
        assert passed is False
        assert "compress" in msg.lower()
        assert meta["needs_har"] is False
        assert meta["needs_compress"] is True
