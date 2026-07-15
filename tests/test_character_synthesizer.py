#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B2.1 character_synthesizer.py 测试

锚定: v0.5.1_升级/00_技术锚定/L1_模块边界与需求索引.md §FR-04
检查点: 多卷角色聚合 / 单卷过滤 / 空输入 / 畸形 id 跳过
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
from character_synthesizer import (  # noqa: E402
    prepare_character_synthesis,
)


# ─── CP-1: 多卷角色聚合（≥2 卷保留并按卷索引排序）─────────────

def test_multi_volume_character():
    """出现在 3 卷的角色应被保留，volumes 按卷索引升序排列。

    注: 卷链由实体 id 解析得出（与 graph_builder.build_evolves_to_relations
    一致），evolves_to_relations 参数为契约预留，此处传空即可。
    """
    # 输入故意打乱卷顺序，验证输出按 vol_idx 升序
    entities = [
        Entity(
            id="C_莫凡__T_main_vol_2",
            name="莫凡",
            type="character",
            info="第三卷档案",
        ),
        Entity(
            id="C_莫凡__T_main_vol_0",
            name="莫凡",
            type="character",
            info="第一卷档案",
        ),
        Entity(
            id="C_莫凡__T_main_vol_1",
            name="莫凡",
            type="character",
            info="第二卷档案",
        ),
    ]

    result = prepare_character_synthesis(entities, [])

    assert len(result) == 1
    assert result[0]["name"] == "莫凡"
    volumes = result[0]["volumes"]
    assert len(volumes) == 3
    # 验证按卷索引升序
    assert [v["vol_idx"] for v in volumes] == [0, 1, 2]
    assert volumes[0]["entity_id"] == "C_莫凡__T_main_vol_0"
    assert volumes[0]["info"] == "第一卷档案"
    assert volumes[2]["entity_id"] == "C_莫凡__T_main_vol_2"
    assert volumes[2]["info"] == "第三卷档案"


# ─── CP-2: 单卷角色过滤 ─────────────────────────────────────

def test_single_volume_filtered():
    """仅出现在 1 卷的角色（含旧格式 id）应被过滤掉。"""
    entities = [
        Entity(
            id="C_张三__T_main_vol_0",
            name="张三",
            type="character",
            info="仅一卷",
        ),
        # 旧格式 id（无卷后缀）— 单卷角色，应被过滤
        Entity(
            id="C_李四",
            name="李四",
            type="character",
            info="旧格式",
        ),
    ]

    result = prepare_character_synthesis(entities, [])

    assert result == []


# ─── CP-3: 空输入 ──────────────────────────────────────────

def test_no_characters():
    """空实体列表应返回空结果。"""
    result = prepare_character_synthesis([], [])

    assert result == []


# ─── CP-4: 畸形 id 优雅跳过 ────────────────────────────────

def test_malformed_id_skipped():
    """id 不匹配 C_{name}__T_main_vol_{idx} 格式或非角色类型应被跳过。"""
    entities = [
        # 畸形 id（缺少 __T_main_vol_ 后缀）— 应跳过
        Entity(
            id="C_王五",
            name="王五",
            type="character",
            info="旧格式",
        ),
        # 畸形 id（前缀非单大写字母_）— 应跳过
        Entity(
            id="CC_赵六__T_main_vol_0",
            name="赵六",
            type="character",
            info="畸形前缀",
        ),
        # 非角色类型（虽 id 格式合法）— 应跳过
        Entity(
            id="L_长安__T_main_vol_0",
            name="长安",
            type="location",
            info="地点",
        ),
        # 合法多卷角色 — 应保留
        Entity(
            id="C_莫凡__T_main_vol_0",
            name="莫凡",
            type="character",
            info="v0",
        ),
        Entity(
            id="C_莫凡__T_main_vol_1",
            name="莫凡",
            type="character",
            info="v1",
        ),
    ]

    result = prepare_character_synthesis(entities, [])

    # 仅保留莫凡（2 卷），畸形 id 与非角色被跳过
    assert len(result) == 1
    assert result[0]["name"] == "莫凡"
    assert len(result[0]["volumes"]) == 2
    assert [v["vol_idx"] for v in result[0]["volumes"]] == [0, 1]
