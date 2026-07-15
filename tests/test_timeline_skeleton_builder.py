#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B2 timeline_skeleton_builder.py 测试

锚定: track_B_plan.md §T-B2
检查点: CP-B2.1 (E_module 实体生成) + CP-B2.2 (T_main 关系仅连接相邻模块)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 tools 目录加入路径（novel-to-graph-skill 目录名含连字符，无法作为 Python 包）
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from models import (  # noqa: E402
    Entity,
    Relation,
)
from timeline_skeleton_builder import (  # noqa: E402
    build_skeleton,
    adjust_skeleton,
    Skeleton,
)
from schema_validator import (  # noqa: E402
    validate_E_module_relation,
)


# ─── 测试数据 ───────────────────────────────────────────────

_PLOT_MODULES_3 = [
    {
        "name": "觉醒篇",
        "chapter_range": [1, 50],
        "theme": "主角觉醒魔法天赋",
        "stage_position": "开局",
    },
    {
        "name": "成长篇",
        "chapter_range": [51, 120],
        "theme": "主角在学院成长历练",
        "stage_position": "发展",
    },
    {
        "name": "决战篇",
        "chapter_range": [121, 200],
        "theme": "主角对抗终极反派",
        "stage_position": "高潮",
    },
]


# ─── CP-B2.1: E_module 实体生成 ─────────────────────────────

class TestEModuleEntityGeneration:
    """验证 plot_modules 正确转为 E_module 实体。"""

    def test_normal_build_returns_entities_and_relations(self):
        """3 个模块 → 3 个 E_module 实体 + 2 个 T_main 关系。"""
        entities, relations = build_skeleton(_PLOT_MODULES_3)
        assert len(entities) == 3
        assert len(relations) == 2

    def test_entity_type_is_E_module(self):
        """每个实体 type 必须为 'E_module'。"""
        entities, _ = build_skeleton(_PLOT_MODULES_3)
        for ent in entities:
            assert ent.type == "E_module"

    def test_entity_id_format(self):
        """实体 ID 格式为 'E_module_{name}'。"""
        entities, _ = build_skeleton(_PLOT_MODULES_3)
        expected_ids = ["E_module_觉醒篇", "E_module_成长篇", "E_module_决战篇"]
        actual_ids = [ent.id for ent in entities]
        assert actual_ids == expected_ids

    def test_entity_name_preserved(self):
        """实体 name 保留原始模块名。"""
        entities, _ = build_skeleton(_PLOT_MODULES_3)
        names = [ent.name for ent in entities]
        assert names == ["觉醒篇", "成长篇", "决战篇"]

    def test_entity_coords_T_equals_own_id(self):
        """E_module.coords.T 字段为自身 ID。"""
        entities, _ = build_skeleton(_PLOT_MODULES_3)
        for ent in entities:
            assert ent.coords["T"] == ent.id, (
                f"coords.T 应为 '{ent.id}'，实际为 '{ent.coords.get('T')}'"
            )

    def test_entity_base_info_stores_metadata(self):
        """实体 base_info 存储 chapter_range/theme/stage_position。"""
        entities, _ = build_skeleton(_PLOT_MODULES_3)
        first = entities[0]
        assert first.base_info.get("chapter_range") == [1, 50]
        assert first.base_info.get("theme") == "主角觉醒魔法天赋"
        assert first.base_info.get("stage_position") == "开局"


# ─── CP-B2.2: T_main 关系仅连接相邻模块 ─────────────────────

class TestTMainRelationAdjacency:
    """验证 T_main 关系仅连接相邻 E_module。"""

    def test_relation_type_is_T_main(self):
        """所有关系 relation_type 固定为 'T_main'。"""
        _, relations = build_skeleton(_PLOT_MODULES_3)
        for rel in relations:
            assert rel.relation_type == "T_main"

    def test_adjacent_modules_connected(self):
        """3 个模块产生 2 条 T_main：模块0→模块1，模块1→模块2。"""
        entities, relations = build_skeleton(_PLOT_MODULES_3)
        assert relations[0].source_id == entities[0].id
        assert relations[0].target_id == entities[1].id
        assert relations[1].source_id == entities[1].id
        assert relations[1].target_id == entities[2].id

    def test_no_skip_connections(self):
        """不存在跨模块连接（模块0→模块2 不应存在）。"""
        entities, relations = build_skeleton(_PLOT_MODULES_3)
        all_pairs = {(r.source_id, r.target_id) for r in relations}
        # 不应存在模块0→模块2 的直连
        skip_pair = (entities[0].id, entities[2].id)
        assert skip_pair not in all_pairs, "不应存在跨模块直连"

    def test_first_module_no_incoming_edge(self):
        """第一个模块无入边（无 T_main 指向它）。"""
        entities, relations = build_skeleton(_PLOT_MODULES_3)
        first_id = entities[0].id
        incoming = [r for r in relations if r.target_id == first_id]
        assert len(incoming) == 0, "第一个模块不应有入边"

    def test_last_module_no_outgoing_edge(self):
        """最后一个模块无出边（无 T_main 从它发出）。"""
        entities, relations = build_skeleton(_PLOT_MODULES_3)
        last_id = entities[-1].id
        outgoing = [r for r in relations if r.source_id == last_id]
        assert len(outgoing) == 0, "最后一个模块不应有出边"

    def test_two_modules_one_relation(self):
        """2 个模块 → 1 条 T_main 关系。"""
        two_modules = _PLOT_MODULES_3[:2]
        entities, relations = build_skeleton(two_modules)
        assert len(entities) == 2
        assert len(relations) == 1
        assert relations[0].source_id == entities[0].id
        assert relations[0].target_id == entities[1].id


# ─── 异常处理 ───────────────────────────────────────────────

class TestExceptions:
    """验证异常边界条件。"""

    def test_empty_list_raises_value_error(self):
        """plot_modules 为空列表时抛 ValueError。"""
        with pytest.raises(ValueError, match="至少需要 2 个"):
            build_skeleton([])

    def test_single_module_raises_value_error(self):
        """plot_modules 仅含 1 个模块时抛 ValueError。"""
        single = [_PLOT_MODULES_3[0]]
        with pytest.raises(ValueError, match="至少需要 2 个"):
            build_skeleton(single)


# ─── 跨轨道协同: 与 validate_E_module_relation 交叉校验 ──────

class TestCrossValidationWithSchemaValidator:
    """验证构建的 T_main 关系通过 validate_E_module_relation 校验。

    锚定: T-B2 跨轨道协同要求 — 与 T-A2 的 validate_E_module_relation 交叉校验。
    """

    def test_built_relations_pass_validation(self):
        """build_skeleton 构建的 T_main 关系必须通过 validate_E_module_relation。"""
        entities, relations = build_skeleton(_PLOT_MODULES_3)
        assert validate_E_module_relation(entities, relations) is True

    def test_built_entities_are_all_E_module_type(self):
        """构建的所有实体 type 为 E_module（validate_E_module_relation 前提）。"""
        entities, _ = build_skeleton(_PLOT_MODULES_3)
        for ent in entities:
            assert ent.type == "E_module"

    def test_five_modules_cross_validation(self):
        """5 个模块的更大规模构建也通过交叉校验。"""
        five_modules = [
            {"name": f"模块{i}", "chapter_range": [i * 10, i * 10 + 9],
             "theme": f"主题{i}", "stage_position": "发展"}
            for i in range(5)
        ]
        entities, relations = build_skeleton(five_modules)
        assert len(entities) == 5
        assert len(relations) == 4
        assert validate_E_module_relation(entities, relations) is True


# ─── CP-P1-6: adjust_skeleton 保留原有 ID ───────────────────

class TestAdjustSkeletonPreservesIds:
    """验证 adjust_skeleton 在重建时保留 existing T_main 卷和 E_module 的 ID。

    锚定: spec.md T-P1-6 / checklist CP-P1-8 / CP-P1-9
    """

    @staticmethod
    def _make_existing_skeleton() -> Skeleton:
        """构造已有 Skeleton：5 卷（达到 MIN_T_MAIN_VOLUMES，不触发 _expand_candidates）。

        每卷配 1 个 E_module，确保 adjust_skeleton 走"追加合并"路径而非扩展/合并路径。
        """
        t_main_volumes = [
            Entity(
                id=f"T_main_vol_existing_{i}",
                name=f"已有卷{i + 1}",
                type="T_main",
                coords={"T": f"T_main_vol_existing_{i}"},
                base_info={
                    "start_chunk": i * 100,
                    "end_chunk": i * 100 + 99,
                    "theme": f"主题{i + 1}",
                    "stage": ["开篇", "发展", "转折", "高潮", "收束"][i],
                    "range": [i * 100, i * 100 + 99],
                },
            )
            for i in range(5)
        ]
        e_modules = [
            Entity(
                id=f"E_module_existing_{i}_0",
                name=f"已有模块{i + 1}",
                type="E_module",
                coords={"T": f"E_module_existing_{i}_0"},
                base_info={
                    "start_chunk": i * 100,
                    "end_chunk": i * 100 + 99,
                    "theme": f"子主题{i + 1}",
                    "parent_volume": f"T_main_vol_existing_{i}",
                },
            )
            for i in range(5)
        ]
        t_main_relations = [
            Relation(
                source_id=f"T_main_vol_existing_{i}",
                target_id=f"T_main_vol_existing_{i + 1}",
                relation_type="T_main",
                strength="strong",
            )
            for i in range(4)
        ]
        has_module_relations = [
            Relation(
                source_id=f"T_main_vol_existing_{i}",
                target_id=f"E_module_existing_{i}_0",
                relation_type="HAS_MODULE",
                strength="strong",
            )
            for i in range(5)
        ]
        # 每卷仅 1 个 E_module，无模块间时序关系
        t_main_module_relations: list[Relation] = []
        return Skeleton(
            t_main_volumes=t_main_volumes,
            e_modules=e_modules,
            t_main_relations=t_main_relations,
            has_module_relations=has_module_relations,
            t_main_module_relations=t_main_module_relations,
        )

    def test_existing_t_main_volume_ids_preserved(self):
        """adjust_skeleton 后原有 T_main 卷的 ID 不变。"""
        existing = self._make_existing_skeleton()
        existing_vol_ids = {vol.id for vol in existing.t_main_volumes}

        # new_cluster 不含 id 的新候选（追加在末尾）
        new_cluster = {
            "t_main_candidates": [
                {
                    "name": "新卷3",
                    "start_chunk": 200,
                    "end_chunk": 299,
                    "range": [200, 299],
                    "theme": "新主题",
                    "stage": "高潮",
                },
            ],
            "module_candidates": [],
        }

        adjusted = adjust_skeleton(existing, new_cluster)
        adjusted_vol_ids = {vol.id for vol in adjusted.t_main_volumes}

        # 原有的 2 个卷 ID 必须保留
        assert existing_vol_ids.issubset(adjusted_vol_ids), (
            f"原有 T_main 卷 ID 必须保留: {existing_vol_ids - adjusted_vol_ids} 丢失"
        )

    def test_existing_e_module_ids_preserved(self):
        """adjust_skeleton 后原有 E_module 的 ID 不变。"""
        existing = self._make_existing_skeleton()
        existing_mod_ids = {mod.id for mod in existing.e_modules}

        new_cluster = {
            "t_main_candidates": [
                {
                    "name": "新卷3",
                    "start_chunk": 200,
                    "end_chunk": 299,
                    "range": [200, 299],
                    "theme": "新主题",
                    "stage": "高潮",
                },
            ],
            "module_candidates": [],
        }

        adjusted = adjust_skeleton(existing, new_cluster)
        adjusted_mod_ids = {mod.id for mod in adjusted.e_modules}

        # 原有 4 个 E_module ID 必须保留
        missing = existing_mod_ids - adjusted_mod_ids
        assert not missing, f"原有 E_module ID 丢失: {missing}"

    def test_new_volume_gets_default_id_when_no_id_in_candidate(self):
        """新追加的候选不含 id 字段时，使用默认 ID 格式 T_main_vol_{i}。"""
        existing = self._make_existing_skeleton()
        existing_ids = {vol.id for vol in existing.t_main_volumes}
        new_cluster = {
            "t_main_candidates": [
                {
                    "name": "新卷6",
                    "start_chunk": 500,
                    "end_chunk": 599,
                    "range": [500, 599],
                    "theme": "新主题",
                    "stage": "尾声",
                },
            ],
            "module_candidates": [],
        }

        adjusted = adjust_skeleton(existing, new_cluster)
        # 排除所有 5 个 existing ID，剩余应为新卷
        new_vols = [v for v in adjusted.t_main_volumes if v.id not in existing_ids]
        assert len(new_vols) == 1, (
            f"应仅 1 个新卷，实际 {len(new_vols)} 个: {[v.id for v in new_vols]}"
        )
        # 新卷使用默认 ID 格式（具体索引由排序决定，但格式必须是 T_main_vol_{i}）
        assert new_vols[0].id.startswith("T_main_vol_"), (
            f"新卷 ID 应为默认格式 T_main_vol_{{i}}，实际为 {new_vols[0].id}"
        )
        # 新卷不应使用 existing_ 前缀
        assert "existing" not in new_vols[0].id, (
            f"新卷 ID 不应包含 existing 前缀: {new_vols[0].id}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
