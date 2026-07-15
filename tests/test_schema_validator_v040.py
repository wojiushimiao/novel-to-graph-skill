#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-A2 schema_validator.py v0.4.0 升级测试

锚定: track_A_plan.md §T-A2
检查点: CP-A2.1 ~ CP-A2.6 (6 个校验函数测试)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 tools 目录加入路径
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from models import (  # noqa: E402
    Entity,
    Relation,
)
from schema_validator import (  # noqa: E402
    validate_coords_unique,
    validate_no_K_dimension,
    validate_info_length,
    validate_E_module_relation,
    validate_relation_desc_length,
    validate_info_cohesion,
    validate_S_topo_bidirectional,
)


# ─── CP-A2.1: validate_coords_unique ──────────────────────

class TestValidateCoordsUnique:
    """验证五维坐标每维度为唯一值（str 而非 list）。"""

    def test_unique_string_values_pass(self):
        """所有维度为 string 值，通过。"""
        coords = {"T": "E_module_1", "L": "L_博城", "C": "C_莫凡", "E": "E_觉醒", "R": "R_power"}
        assert validate_coords_unique(coords) is True

    def test_list_value_fails(self):
        """维度为 list 值，拒绝。"""
        coords = {"T": ["E_module_1", "E_module_2"], "L": "L_博城", "C": "C_莫凡", "E": "E_觉醒", "R": "R_power"}
        assert validate_coords_unique(coords) is False

    def test_partial_list_fails(self):
        """任一维度为 list，拒绝。"""
        coords = {"T": "E_module_1", "L": ["L_博城", "L_上海"], "C": "C_莫凡", "E": "E_觉醒", "R": "R_power"}
        assert validate_coords_unique(coords) is False

    def test_empty_string_passes(self):
        """空字符串视为唯一值，通过。"""
        coords = {"T": "", "L": "", "C": "", "E": "", "R": ""}
        assert validate_coords_unique(coords) is True


# ─── CP-A2.2: validate_info_length ─────────────────────────

class TestValidateInfoLength:
    """验证 info 字数校验（500-1500 通过, <500 拒绝, >1500 触发压缩）。"""

    def test_too_short_reject(self):
        """字数 <500 拒绝。"""
        info = "a" * 499
        passed, msg = validate_info_length(info)
        assert passed is False
        assert "不足" in msg or "short" in msg.lower()

    def test_min_boundary_pass(self):
        """字数 = 500 通过（含边界）。"""
        info = "a" * 500
        passed, msg = validate_info_length(info)
        assert passed is True

    def test_normal_range_pass(self):
        """字数 500-1500 通过。"""
        info = "a" * 1000
        passed, msg = validate_info_length(info)
        assert passed is True

    def test_max_boundary_pass(self):
        """字数 = 1500 通过（含边界）。"""
        info = "a" * 1500
        passed, msg = validate_info_length(info)
        assert passed is True

    def test_too_long_trigger_compress(self):
        """字数 >1500 触发压缩。"""
        info = "a" * 1501
        passed, msg = validate_info_length(info)
        assert passed is False
        assert "压缩" in msg or "compress" in msg.lower()


# ─── CP-A2.3: validate_E_module_relation ──────────────────

class TestValidateEModuleRelation:
    """验证 T_main 仅连接 E_module→E_module。"""

    def test_valid_T_main_pass(self):
        """T_main 连接 E_module→E_module，通过。"""
        entities = [
            Entity(id="E_module_1", name="模块1", type="E_module"),
            Entity(id="E_module_2", name="模块2", type="E_module"),
        ]
        relations = [
            Relation(source_id="E_module_1", target_id="E_module_2", relation_type="T_main"),
        ]
        assert validate_E_module_relation(entities, relations) is True

    def test_T_main_to_non_E_module_fails(self):
        """T_main 连接 E_module→character，拒绝。"""
        entities = [
            Entity(id="E_module_1", name="模块1", type="E_module"),
            Entity(id="C_莫凡", name="莫凡", type="character"),
        ]
        relations = [
            Relation(source_id="E_module_1", target_id="C_莫凡", relation_type="T_main"),
        ]
        assert validate_E_module_relation(entities, relations) is False

    def test_T_main_from_non_E_module_fails(self):
        """T_main 连接 character→E_module，拒绝。"""
        entities = [
            Entity(id="C_莫凡", name="莫凡", type="character"),
            Entity(id="E_module_1", name="模块1", type="E_module"),
        ]
        relations = [
            Relation(source_id="C_莫凡", target_id="E_module_1", relation_type="T_main"),
        ]
        assert validate_E_module_relation(entities, relations) is False

    def test_non_T_main_relations_ignored(self):
        """非 T_main 关系不受约束。"""
        entities = [
            Entity(id="E_module_1", name="模块1", type="E_module"),
            Entity(id="C_莫凡", name="莫凡", type="character"),
        ]
        relations = [
            Relation(source_id="E_module_1", target_id="C_莫凡", relation_type="R_strong"),
        ]
        assert validate_E_module_relation(entities, relations) is True

    def test_empty_relations_pass(self):
        """空关系列表，通过。"""
        entities = [Entity(id="E_module_1", name="模块1", type="E_module")]
        relations = []
        assert validate_E_module_relation(entities, relations) is True


# ─── CP-A2.4: validate_relation_desc_length ───────────────

class TestValidateRelationDescLength:
    """验证关系 description 长度校验（≤50 通过, 50-100 标记, >100 拒绝）。"""

    def test_short_pass(self):
        """≤50 字通过。"""
        desc = "a" * 50
        passed, msg = validate_relation_desc_length(desc)
        assert passed is True
        assert msg == "pass"

    def test_empty_pass(self):
        """空字符串通过。"""
        passed, msg = validate_relation_desc_length("")
        assert passed is True
        assert msg == "pass"

    def test_warn_suspicious(self):
        """50-100 字标记疑似分散。"""
        desc = "a" * 51
        passed, msg = validate_relation_desc_length(desc)
        assert passed is True
        assert "suspicious" in msg or "warn" in msg.lower()

    def test_warn_boundary_100(self):
        """=100 字仍为标记（边界含）。"""
        desc = "a" * 100
        passed, msg = validate_relation_desc_length(desc)
        assert passed is True
        assert "suspicious" in msg or "warn" in msg.lower()

    def test_too_long_reject(self):
        """>100 字拒绝。"""
        desc = "a" * 101
        passed, msg = validate_relation_desc_length(desc)
        assert passed is False
        assert "reject" in msg.lower() or "too_long" in msg.lower()


# ─── CP-A2.5: validate_info_cohesion ──────────────────────

class TestValidateInfoCohesion:
    """验证节点详情内聚于 info 字段。"""

    def test_good_info_pass(self):
        """info 充分（≥500字）且出边 description 简短，通过。"""
        entity = Entity(
            id="C_莫凡", name="莫凡", type="character",
            info="a" * 800,
        )
        relations = [
            Relation(source_id="C_莫凡", target_id="C_叶心夏", relation_type="R_strong", description="恋人"),
        ]
        passed, msg = validate_info_cohesion(entity, relations)
        assert passed is True

    def test_short_info_many_edges_warn(self):
        """info <500字 且 出边数 ≥3，标记疑似分散。"""
        entity = Entity(
            id="C_莫凡", name="莫凡", type="character",
            info="a" * 200,
        )
        relations = [
            Relation(source_id="C_莫凡", target_id="C_叶心夏", relation_type="R_strong", description="恋人"),
            Relation(source_id="C_莫凡", target_id="C_张小侯", relation_type="R_strong", description="挚友"),
            Relation(source_id="C_莫凡", target_id="C_赵满延", relation_type="R_strong", description="同窗"),
        ]
        passed, msg = validate_info_cohesion(entity, relations)
        # 疑似分散应标记（passed=True 但 warn，或 passed=False 标记）
        assert "cohesive" in msg.lower() or "分散" in msg or "suspect" in msg.lower() or "warn" in msg.lower() or passed is False

    def test_long_relation_desc_reject(self):
        """出边 description >100字，拒绝。"""
        entity = Entity(
            id="C_莫凡", name="莫凡", type="character",
            info="a" * 800,
        )
        relations = [
            Relation(
                source_id="C_莫凡", target_id="C_叶心夏",
                relation_type="R_strong",
                description="b" * 150,
            ),
        ]
        passed, msg = validate_info_cohesion(entity, relations)
        assert passed is False
        assert "reject" in msg.lower() or "分散" in msg or "long" in msg.lower()

    def test_no_relations_pass(self):
        """无出边，通过。"""
        entity = Entity(
            id="C_莫凡", name="莫凡", type="character",
            info="a" * 200,
        )
        relations = []
        passed, msg = validate_info_cohesion(entity, relations)
        assert passed is True


# ─── CP-A2.6: validate_S_topo_bidirectional ───────────────

class TestValidateSTopoBidirectional:
    """验证 S_topo 双向: 实体→L + L→E_module/E_event。"""

    def test_valid_bidirectional_pass(self):
        """完整双向 S_topo，通过。
        
        L6入边: 实体→L
        L7出边: L→E_module/E_event
        """
        relations = [
            # L6入边: 实体→L
            {"source_id": "E_module_1", "target_id": "L_博城", "relation_type": "S_topo"},
            # L7出边: L→E_module
            {"source_id": "L_博城", "target_id": "E_module_1", "relation_type": "S_topo"},
        ]
        assert validate_S_topo_bidirectional(relations) is True

    def test_only_inbound_fails(self):
        """仅入边（实体→L），无出边，拒绝。"""
        relations = [
            {"source_id": "E_module_1", "target_id": "L_博城", "relation_type": "S_topo"},
        ]
        assert validate_S_topo_bidirectional(relations) is False

    def test_only_outbound_fails(self):
        """仅出边（L→E_module），无入边，拒绝。"""
        relations = [
            {"source_id": "L_博城", "target_id": "E_module_1", "relation_type": "S_topo"},
        ]
        assert validate_S_topo_bidirectional(relations) is False

    def test_no_S_topo_pass(self):
        """无 S_topo 关系，通过（不强制要求存在）。"""
        relations = [
            {"source_id": "E_module_1", "target_id=": "E_module_2", "relation_type": "T_main"},
        ]
        # 修正：确保测试数据正确
        relations = [
            {"source_id": "E_module_1", "target_id": "E_module_2", "relation_type": "T_main"},
        ]
        assert validate_S_topo_bidirectional(relations) is True

    def test_non_S_topo_ignored(self):
        """非 S_topo 关系被忽略。"""
        relations = [
            {"source_id": "E_module_1", "target_id": "E_module_2", "relation_type": "T_main"},
            {"source_id": "C_莫凡", "target_id": "C_叶心夏", "relation_type": "R_strong"},
        ]
        assert validate_S_topo_bidirectional(relations) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
