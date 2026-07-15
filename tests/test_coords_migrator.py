#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-C1 coords_migrator.py 测试

锚定: track_C_plan.md §T-C1
检查点: CP-C1.1 (旧六维→新五维迁移正确) + CP-C1.2 (K 维度被移除)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 tools 目录加入路径，直接导入模块（避免与 06_核心代码/tools 包名冲突）
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from coords_migrator import migrate_coords  # noqa: E402
from schema_validator import (  # noqa: E402
    validate_coords_unique,
    validate_no_K_dimension,
)


# ─── CP-C1.1: 旧六维→新五维迁移正确 ────────────────────────

class TestNormalMigration:
    """验证旧六维多值坐标正确迁移到新五维唯一值。"""

    def test_full_six_dim_to_five_dim(self):
        """完整的六维多值坐标迁移到五维唯一值。"""
        old_coords = {
            "T": ["E_module_1", "E_module_2"],
            "L": ["L_博城", "L_上海"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
            "K": ["K_主线"],
            "R": {"R_power": "力量体系"},
        }
        result = migrate_coords(old_coords)
        assert result["T"] == "E_module_1"
        assert result["L"] == "L_博城"
        assert result["C"] == "C_莫凡"
        assert result["E"] == "E_觉醒"
        assert result["R"] == "力量体系"

    def test_first_non_empty_from_list(self):
        """列表含空字符串时取第一个非空值。"""
        old_coords = {
            "T": ["", "E_module_2", "E_module_3"],
            "L": ["", "", "L_上海"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
        }
        result = migrate_coords(old_coords)
        assert result["T"] == "E_module_2"
        assert result["L"] == "L_上海"

    def test_string_value_not_list(self):
        """T/L/C/E 为字符串（非列表）时直接使用。"""
        old_coords = {
            "T": "E_module_1",
            "L": "L_博城",
            "C": "C_莫凡",
            "E": "E_觉醒",
        }
        result = migrate_coords(old_coords)
        assert result["T"] == "E_module_1"
        assert result["L"] == "L_博城"

    def test_empty_list_fills_empty_string(self):
        """空列表填充为空字符串。"""
        old_coords = {
            "T": [],
            "L": [],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
        }
        result = migrate_coords(old_coords)
        assert result["T"] == ""
        assert result["L"] == ""

    def test_all_empty_strings_in_list(self):
        """列表全为空字符串时填充为空字符串。"""
        old_coords = {
            "T": ["", "", ""],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
        }
        result = migrate_coords(old_coords)
        assert result["T"] == ""


class TestMissingDimensions:
    """验证缺失维度填充为空字符串。"""

    def test_missing_T_filled_empty(self):
        """缺失 T 维度时填充为空字符串。"""
        old_coords = {
            "L": ["L_博城"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
        }
        result = migrate_coords(old_coords)
        assert result["T"] == ""

    def test_missing_all_but_one(self):
        """仅含 C 维度时其余填充为空字符串。"""
        old_coords = {"C": ["C_莫凡"]}
        result = migrate_coords(old_coords)
        assert result["T"] == ""
        assert result["L"] == ""
        assert result["C"] == "C_莫凡"
        assert result["E"] == ""
        assert result["R"] == ""

    def test_missing_R_filled_empty(self):
        """缺失 R 维度时填充为空字符串。"""
        old_coords = {
            "T": ["E_module_1"],
            "L": ["L_博城"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
        }
        result = migrate_coords(old_coords)
        assert result["R"] == ""

    def test_output_has_exactly_five_dims(self):
        """输出恰好包含五维 T/L/C/E/R。"""
        old_coords = {
            "T": ["E_module_1"],
            "L": ["L_博城"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
            "K": ["K_主线"],
            "R": {"R_power": "力量体系"},
        }
        result = migrate_coords(old_coords)
        assert set(result.keys()) == {"T", "L", "C", "E", "R"}


# ─── CP-C1.2: K 维度被移除 ─────────────────────────────────

class TestKDimensionRemoved:
    """验证 K 维度被移除。"""

    def test_K_not_in_output(self):
        """迁移后输出不含 K 维度。"""
        old_coords = {
            "T": ["E_module_1"],
            "L": ["L_博城"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
            "K": ["K_主线", "K_支线"],
        }
        result = migrate_coords(old_coords)
        assert "K" not in result

    def test_K_with_multiple_values_removed(self):
        """K 含多值时仍被移除。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "K": ["K_主线", "K_副线", "K_隐线"],
        }
        result = migrate_coords(old_coords)
        assert "K" not in result


# ─── R 维度从 dict 转为 string ─────────────────────────────

class TestRDimensionConversion:
    """验证 R 维度从字典转为字符串。"""

    def test_R_dict_single_entry(self):
        """R 字典含单条目时取其值。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "R": {"R_power": "力量体系"},
        }
        result = migrate_coords(old_coords)
        assert result["R"] == "力量体系"

    def test_R_dict_multiple_entries(self):
        """R 字典含多条目时取第一个非空值。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "R": {"R_power": "", "R_cultivation": "修真体系"},
        }
        result = migrate_coords(old_coords)
        assert result["R"] == "修真体系"

    def test_R_empty_dict(self):
        """R 为空字典时填充为空字符串。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "R": {},
        }
        result = migrate_coords(old_coords)
        assert result["R"] == ""

    def test_R_all_empty_values(self):
        """R 字典所有值为空时填充为空字符串。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "R": {"R_power": "", "R_cultivation": ""},
        }
        result = migrate_coords(old_coords)
        assert result["R"] == ""

    def test_R_already_string(self):
        """R 已是字符串时保持不变。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "R": "R_power",
        }
        result = migrate_coords(old_coords)
        assert result["R"] == "R_power"

    def test_R_none_value(self):
        """R 为 None 时填充为空字符串。"""
        old_coords = {
            "T": ["E_module_1"],
            "C": ["C_莫凡"],
            "R": None,
        }
        result = migrate_coords(old_coords)
        assert result["R"] == ""


# ─── 无 T/L/C/E 时抛 KeyError ──────────────────────────────

class TestKeyErrorOnMissingAllDims:
    """验证 old_coords 无 T/L/C/E 任意一维时抛 KeyError。"""

    def test_empty_dict_raises(self):
        """空字典抛 KeyError。"""
        with pytest.raises(KeyError):
            migrate_coords({})

    def test_only_K_and_R_raises(self):
        """仅含 K 和 R 维度时抛 KeyError。"""
        old_coords = {
            "K": ["K_主线"],
            "R": {"R_power": "力量体系"},
        }
        with pytest.raises(KeyError):
            migrate_coords(old_coords)

    def test_only_K_raises(self):
        """仅含 K 维度时抛 KeyError。"""
        with pytest.raises(KeyError):
            migrate_coords({"K": ["K_主线"]})

    def test_only_R_raises(self):
        """仅含 R 维度时抛 KeyError。"""
        with pytest.raises(KeyError):
            migrate_coords({"R": {"R_power": "力量体系"}})


# ─── 迁移后通过校验函数 ────────────────────────────────────

class TestPostMigrationValidation:
    """验证迁移后通过 validate_coords_unique + validate_no_K_dimension。"""

    def test_passes_validate_coords_unique(self):
        """迁移后通过 validate_coords_unique。"""
        old_coords = {
            "T": ["E_module_1", "E_module_2"],
            "L": ["L_博城"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
            "K": ["K_主线"],
            "R": {"R_power": "力量体系"},
        }
        result = migrate_coords(old_coords)
        assert validate_coords_unique(result) is True

    def test_passes_validate_no_K_dimension(self):
        """迁移后通过 validate_no_K_dimension。"""
        old_coords = {
            "T": ["E_module_1"],
            "L": ["L_博城"],
            "C": ["C_莫凡"],
            "E": ["E_觉醒"],
            "K": ["K_主线"],
            "R": {"R_power": "力量体系"},
        }
        result = migrate_coords(old_coords)
        assert validate_no_K_dimension(result) is True

    def test_partial_coords_passes_validation(self):
        """仅含部分维度的坐标迁移后仍通过校验。"""
        old_coords = {"C": ["C_莫凡"]}
        result = migrate_coords(old_coords)
        assert validate_coords_unique(result) is True
        assert validate_no_K_dimension(result) is True

    def test_empty_values_pass_validation(self):
        """迁移后含空字符串的维度仍通过校验。"""
        old_coords = {
            "T": [],
            "C": ["C_莫凡"],
        }
        result = migrate_coords(old_coords)
        assert validate_coords_unique(result) is True
        assert validate_no_K_dimension(result) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
