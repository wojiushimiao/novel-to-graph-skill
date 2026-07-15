#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-A1 models.py v0.4.0 升级测试

锚定: track_A_plan.md §T-A1
检查点: CP-A1.1 (E_module 类型识别) + CP-A1.2 (COORD_DIMENSIONS 五维)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 tools 目录加入路径（novel-analysis-skill 目录名含连字符，无法作为 Python 包）
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from models import (  # noqa: E402
    Entity,
    ENTITY_TYPES,
    ENTITY_OUT_EDGE_LIMITS,
    COORD_DIMENSIONS,
)


# ─── CP-A1.1: E_module 类型识别 ────────────────────────────

class TestEModuleType:
    """验证 E_module 实体子类型可被识别。"""

    def test_E_module_in_ENTITY_TYPES(self):
        """E_module 必须在 ENTITY_TYPES 常量中。"""
        assert "E_module" in ENTITY_TYPES, "ENTITY_TYPES 必须包含 'E_module'"

    def test_E_module_entity_constructable(self):
        """type='E_module' 的 Entity 可构造。"""
        entity = Entity(
            id="E_module_测试模块",
            name="测试模块",
            type="E_module",
        )
        assert entity.type == "E_module"
        assert entity.type in ENTITY_TYPES, "E_module 必须在 ENTITY_TYPES 中"

    def test_existing_types_preserved(self):
        """现有 8 类实体类型不破坏。"""
        expected_existing = {
            "character", "location", "event", "item",
            "rule", "system", "monster", "knowledge",
        }
        for t in expected_existing:
            assert t in ENTITY_TYPES, f"现有类型 '{t}' 必须保留"


# ─── CP-A1.2: COORD_DIMENSIONS 五维（移除 K）──────────────

class TestCoordDimensions:
    """验证 COORD_DIMENSIONS 常量为五维，移除 K 维度。"""

    def test_K_not_in_COORD_DIMENSIONS(self):
        """COORD_DIMENSIONS 不含 K 维度。"""
        assert "K" not in COORD_DIMENSIONS, "COORD_DIMENSIONS 不应包含 'K'"

    def test_five_dimensions_complete(self):
        """五维 [T, L, C, E, R] 完整。"""
        expected = ("T", "L", "C", "E", "R")
        assert COORD_DIMENSIONS == expected, (
            f"COORD_DIMENSIONS 应为 {expected}, 实际为 {COORD_DIMENSIONS}"
        )

    def test_dimensions_count(self):
        """维度数为 5。"""
        assert len(COORD_DIMENSIONS) == 5


# ─── S_topo 微调: location 出边限制 ────────────────────────

class TestLocationOutEdgeLimit:
    """验证 location 实体允许 S_topo 出边（微调点 S_topo 平行主轴提升）。"""

    def test_location_out_edge_limit_positive(self):
        """location 出边限制 > 0（允许 L→E_module/E_event 出边）。

        v0.3.0: location 出边 = 0（不扇出）
        v0.4.0 微调: location 出边 ≤20（S_topo 平行主轴）
        """
        assert ENTITY_OUT_EDGE_LIMITS["location"] > 0, (
            "v0.4.0 微调后 location 必须允许出边（S_topo 平行主轴）"
        )

    def test_location_out_edge_limit_within_range(self):
        """location 出边限制 ≤20。"""
        assert ENTITY_OUT_EDGE_LIMITS["location"] <= 20, (
            "location 出边上限应为 ≤20（S_topo 空间索引扇出限制）"
        )


# ─── 向后兼容性测试 ─────────────────────────────────────────

class TestBackwardCompatibility:
    """验证现有工具不破坏。"""

    def test_existing_entity_types_unchanged(self):
        """现有 8 类实体类型保留。"""
        existing_types = {
            "character", "location", "event", "item",
            "rule", "system", "monster", "knowledge",
        }
        for t in existing_types:
            assert t in ENTITY_TYPES

    def test_existing_out_edge_limits_preserved(self):
        """现有非 location 实体的出边限制保留。"""
        # character 出边应为 5（v0.3.0 保留）
        assert ENTITY_OUT_EDGE_LIMITS["character"] == 5
        # event 出边应为 3
        assert ENTITY_OUT_EDGE_LIMITS["event"] == 3
        # item/rule/system 不变（0）
        for t in ("item", "rule", "system", "monster", "knowledge"):
            assert ENTITY_OUT_EDGE_LIMITS[t] == 0

    def test_Entity_dataclass_constructable(self):
        """Entity dataclass 可正常构造。"""
        entity = Entity(
            id="C_测试",
            name="测试角色",
            type="character",
        )
        assert entity.id == "C_测试"
        assert entity.name == "测试角色"
        assert entity.type == "character"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
