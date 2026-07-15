#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-D.1/T-D.2/T-D.3 多档案并行测试
锚定: v0.5.0 plan.md §T-D.1 / §T-D.2 / §T-D.3
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# novel-to-graph-skill 目录名含连字符，无法作为 Python 包；
# 把 SKILL_DIR 放到 sys.path 最前面，确保 tools 解析到本技能的 tools 目录。
for _mod in list(sys.modules):
    if _mod == "tools" or _mod.startswith("tools."):
        del sys.modules[_mod]

_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) in sys.path:
    sys.path.remove(str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from tools.models import Entity, Relation  # noqa: E402
from tools.timeline_skeleton_builder import Skeleton  # noqa: E402
from tools.graph_builder import build_evolves_to_relations  # noqa: E402


def _make_character_entity(name, vol_idx):
    """构造角色实体。"""
    return Entity(
        id=f"C_{name}__T_main_vol_{vol_idx}",
        name=name,
        type="character",
    )


def _make_location_entity(name):
    """构造地点实体。"""
    return Entity(
        id=f"L_{name}",
        name=name,
        type="location",
    )


# ─── T-D.1: evolves_to 关系测试 ────────────────────────────

class TestEvolvesToRelations:
    """CP-D.1-D.4: build_evolves_to_relations() 测试。"""

    def test_three_volumes_generates_two_relations(self):
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
            _make_character_entity("莫凡", 2),
        ]
        rels = build_evolves_to_relations(entities)
        assert len(rels) == 2

    def test_two_volumes_generates_one_relation(self):
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
        ]
        rels = build_evolves_to_relations(entities)
        assert len(rels) == 1

    def test_single_volume_generates_no_relations(self):
        entities = [_make_character_entity("莫凡", 0)]
        rels = build_evolves_to_relations(entities)
        assert len(rels) == 0

    def test_empty_entities_returns_empty(self):
        rels = build_evolves_to_relations([])
        assert rels == []

    def test_non_character_entities_ignored(self):
        entities = [_make_location_entity("博城")]
        rels = build_evolves_to_relations(entities)
        assert len(rels) == 0

    def test_relation_strength_is_strong(self):
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
        ]
        rels = build_evolves_to_relations(entities)
        assert rels[0].strength == "strong"

    def test_relation_type_is_evolves_to(self):
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
        ]
        rels = build_evolves_to_relations(entities)
        assert rels[0].relation_type == "evolves_to"

    def test_multi_character_mixed(self):
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
            _make_character_entity("叶心夏", 0),
            _make_character_entity("叶心夏", 1),
            _make_character_entity("叶心夏", 2),
        ]
        rels = build_evolves_to_relations(entities)
        # 莫凡: 0→1 (1条), 叶心夏: 0→1, 1→2 (2条) = 3条
        assert len(rels) == 3

    def test_unsorted_volumes_still_ordered(self):
        """实体传入顺序乱序，关系仍按卷索引排序。"""
        entities = [
            _make_character_entity("莫凡", 2),
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
        ]
        rels = build_evolves_to_relations(entities)
        assert len(rels) == 2
        assert "第0卷" in rels[0].description
        assert "第1卷" in rels[1].description


# ─── T-D.2: 合并器测试 ─────────────────────────────────────

class TestEntityMergerMultiProfile:
    """CP-D.5-D.8: entity_merger 多档案合并键测试。"""

    def test_different_volume_characters_not_merged(self):
        from tools.entity_merger import merge
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
        ]
        merged, _ = merge(entities, [])
        assert len(merged) == 2  # 不同卷不合并

    def test_same_volume_characters_merged(self):
        from tools.entity_merger import merge
        e1 = _make_character_entity("莫凡", 0)
        e1.base_info = {"first_appearance": "第1章"}
        e2 = _make_character_entity("莫凡", 0)
        e2.base_info = {"aliases": ["小莫"]}
        merged, _ = merge([e1, e2], [])
        assert len(merged) == 1  # 同卷合并
        assert "aliases" in merged[0].base_info

    def test_non_character_types_merged_as_before(self):
        from tools.entity_merger import merge
        e1 = _make_location_entity("博城")
        e1.base_info = {"first_appearance": "第1章"}
        e2 = _make_location_entity("博城")
        e2.base_info = {"aliases": ["博城"]}
        merged, _ = merge([e1, e2], [])
        assert len(merged) == 1  # 非角色类型仍合并

    def test_mixed_character_and_location(self):
        from tools.entity_merger import merge
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
            _make_location_entity("博城"),
            _make_location_entity("博城"),
        ]
        merged, _ = merge(entities, [])
        # 莫凡: 2个（不同卷），博城: 1个（合并） = 3个
        assert len(merged) == 3


# ─── T-D.3: 导出器测试 ─────────────────────────────────────

class TestExporterMultiProfile:
    """CP-D.9-D.11: exporter to_markdown() 多档案聚合测试。"""

    def test_group_by_character_enabled(self):
        from tools.exporter import to_markdown
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
            _make_character_entity("莫凡", 2),
        ]
        for i, e in enumerate(entities):
            e.info = f"第{i}卷的莫凡档案内容"
        result = to_markdown(None, entities, [], {"node_count": 3, "edge_count": 0, "density": 0}, group_by_character=True)
        assert "人物弧光总览" in result
        assert "莫凡" in result
        assert "3卷" in result

    def test_group_by_character_disabled(self):
        from tools.exporter import to_markdown
        entities = [
            _make_character_entity("莫凡", 0),
            _make_character_entity("莫凡", 1),
        ]
        result = to_markdown(None, entities, [], {"node_count": 2, "edge_count": 0, "density": 0}, group_by_character=False)
        assert "人物弧光总览" not in result

    def test_non_character_unaffected(self):
        from tools.exporter import to_markdown
        entities = [_make_location_entity("博城")]
        result = to_markdown(None, entities, [], {"node_count": 1, "edge_count": 0, "density": 0}, group_by_character=True)
        assert "博城" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])