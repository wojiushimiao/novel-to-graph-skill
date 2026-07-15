#!/usr/bin/env python3
"""novel-analysis-skill · T-C.1/T-C.2 差异化 Info Schema 测试
锚定: v0.5.0 plan.md §T-C.1 / §T-C.2
"""

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from models import get_info_schema, INFO_SCHEMA  # noqa: E402
from schema_validator import validate_info_structure  # noqa: E402


# ─── Schema 获取测试 ────────────────────────────────────────

class TestGetInfoSchema:
    """CP-C.2: get_info_schema() 按类型返回正确 Schema。"""

    def test_event_returns_four_sections(self):
        schema = get_info_schema("event")
        assert len(schema) == 4
        assert schema[0][0] == "起因"

    def test_character_returns_five_sections(self):
        schema = get_info_schema("character")
        assert len(schema) == 5
        names = [s[0] for s in schema]
        assert "身份背景" in names
        assert "人物弧光" in names

    def test_location_returns_four_sections(self):
        schema = get_info_schema("location")
        assert len(schema) == 4

    def test_item_returns_four_sections(self):
        schema = get_info_schema("item")
        assert len(schema) == 4

    def test_rule_returns_four_sections(self):
        schema = get_info_schema("rule")
        assert len(schema) == 4

    def test_system_returns_four_sections(self):
        schema = get_info_schema("system")
        assert len(schema) == 4

    def test_unknown_type_returns_empty(self):
        assert get_info_schema("unknown") == ()


# ─── 校验测试 ──────────────────────────────────────────────

def _make_info(sections_and_content):
    """构造 info 字符串。"""
    parts = []
    for section, content in sections_and_content:
        parts.append(f"【{section}】{content}")
    return "\n".join(parts)


class TestValidateInfoStructure:
    """CP-C.1/C.3: validate_info_structure() 按类型校验。"""

    def test_event_valid_passes(self):
        info = _make_info([
            ("起因", "起因描述" * 25),
            ("经过", "经过描述" * 50),
            ("结果", "结果描述" * 25),
            ("模块定位", "模块定位" * 25),
        ])
        ok, msg = validate_info_structure(info, "event")
        assert ok, msg

    def test_event_missing_section_fails(self):
        info = _make_info([
            ("起因", "起因描述" * 25),
            ("经过", "经过描述" * 50),
            ("模块定位", "模块定位" * 25),
        ])
        ok, msg = validate_info_structure(info, "event")
        assert not ok
        assert "结果" in msg

    def test_character_valid_passes(self):
        info = _make_info([
            ("身份背景", "背景描述" * 25),
            ("性格特征", "性格描述" * 25),
            ("能力体系", "能力描述" * 25),
            ("人际关系", "关系描述" * 25),
            ("人物弧光", "弧光描述" * 25),
        ])
        ok, msg = validate_info_structure(info, "character")
        assert ok, msg

    def test_character_missing_section_fails(self):
        info = _make_info([
            ("身份背景", "背景描述" * 25),
            ("性格特征", "性格描述" * 25),
            ("能力体系", "能力描述" * 25),
            ("人际关系", "关系描述" * 25),
        ])
        ok, msg = validate_info_structure(info, "character")
        assert not ok

    def test_location_valid_passes(self):
        info = _make_info([
            ("地理描述", "地理描述" * 25),
            ("政治经济", "政治经济" * 25),
            ("关联角色", "关联角色" * 25),
            ("剧情作用", "剧情作用" * 25),
        ])
        ok, msg = validate_info_structure(info, "location")
        assert ok, msg

    def test_non_event_no_src_marker_passes(self):
        """非事件类型不强制 [src:chunk_NNN] 标记。"""
        info = _make_info([
            ("身份背景", "背景描述" * 25),
            ("性格特征", "性格描述" * 25),
            ("能力体系", "能力描述" * 25),
            ("人际关系", "关系描述" * 25),
            ("人物弧光", "弧光描述" * 25),
        ])
        # No [src:chunk_NNN] markers at all
        ok, msg = validate_info_structure(info, "character")
        assert ok, f"非事件类型不应因缺失 src 标记而失败: {msg}"

    def test_unknown_type_passes(self):
        ok, msg = validate_info_structure("any text", "unknown_type")
        assert ok

    def test_backward_compat_no_entity_type(self):
        """不传 entity_type 时默认 event，向后兼容。"""
        info = _make_info([
            ("起因", "起因描述" * 25),
            ("经过", "经过描述" * 50),
            ("结果", "结果描述" * 25),
            ("模块定位", "模块定位" * 25),
        ])
        ok, msg = validate_info_structure(info)
        assert ok, msg

    def test_empty_info_fails(self):
        ok, msg = validate_info_structure("", "event")
        assert not ok


# ─── T-C.2: HAR prompt 测试 ─────────────────────────────────

class TestGenerateHarPrompt:
    """CP-C.5-C.7: generate_har_prompt() 按类型生成 prompt。"""

    def test_event_prompt_contains_four_sections(self):
        from har_refiner import generate_har_prompt
        prompt = generate_har_prompt("event", "test info", "test chunk")
        assert "【起因】" in prompt
        assert "【经过】" in prompt
        assert "【结果】" in prompt
        assert "【模块定位】" in prompt

    def test_event_prompt_contains_src_marker_requirement(self):
        from har_refiner import generate_har_prompt
        prompt = generate_har_prompt("event", "test info", "test chunk")
        assert "[src:chunk_NNN]" in prompt

    def test_character_prompt_contains_five_sections(self):
        from har_refiner import generate_har_prompt
        prompt = generate_har_prompt("character", "test info", "test chunk")
        assert "【身份背景】" in prompt
        assert "【性格特征】" in prompt
        assert "【能力体系】" in prompt
        assert "【人际关系】" in prompt
        assert "【人物弧光】" in prompt

    def test_character_prompt_no_src_marker_requirement(self):
        from har_refiner import generate_har_prompt
        prompt = generate_har_prompt("character", "test info", "test chunk")
        assert "每段末尾必须附加 [src:chunk_NNN]" not in prompt

    def test_location_prompt_contains_correct_sections(self):
        from har_refiner import generate_har_prompt
        prompt = generate_har_prompt("location", "test info", "test chunk")
        assert "【地理描述】" in prompt
        assert "【剧情作用】" in prompt

    def test_unknown_type_falls_back_to_event(self):
        from har_refiner import generate_har_prompt
        prompt = generate_har_prompt("unknown", "test info", "test chunk")
        assert "【起因】" in prompt  # 回退到 event Schema


if __name__ == "__main__":
    pytest.main([__file__, "-v"])