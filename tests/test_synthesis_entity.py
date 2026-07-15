#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""create_synthesis_entity 单元测试（v0.5.1 B2 · T-B2.3）。

锚定: schema_specification.md §4.8 人物小传 Schema
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from models import Entity
from character_synthesizer import create_synthesis_entity


def test_create_synthesis_normal():
    """正常创建: name="莫凡", 验证 id/coords/detail_info/base_info。"""
    info_text = (
        "【身份概述】莫凡是一名普通学生，意外觉醒雷系魔法。"
        "【性格演变】从青涩少年逐渐成长为有担当的法师。"
        "【能力成长】由单系觉醒至双系法师，能力跃升。"
        "【关系网络】与张小候为同窗挚友，与导师建立师徒关系。"
        "【人物弧光】从平凡到非凡的完整蜕变轨迹。"
    )
    entity = create_synthesis_entity(
        name="莫凡",
        info=info_text,
        volumes_covered=[0, 1, 2],
        source_profiles=[
            "C_莫凡__T_main_vol_0",
            "C_莫凡__T_main_vol_1",
            "C_莫凡__T_main_vol_2",
        ],
    )

    # 类型校验
    assert isinstance(entity, Entity)

    # id / name / type
    assert entity.id == "C_莫凡__synthesis"
    assert entity.name == "莫凡"
    assert entity.type == "character"

    # coords
    assert entity.coords == {"T": "synthesis", "C": "莫凡"}

    # base_info — importance 因 Entity 无该字段，落入 base_info
    assert entity.base_info["category"] == "synthesis"
    assert entity.base_info["volumes_count"] == 3
    assert entity.base_info["importance"] == "high"

    # detail_info
    assert entity.detail_info["volumes_covered"] == [0, 1, 2]
    assert entity.detail_info["source_profiles"] == [
        "C_莫凡__T_main_vol_0",
        "C_莫凡__T_main_vol_1",
        "C_莫凡__T_main_vol_2",
    ]

    # info 内容回写
    assert "身份概述" in entity.info
    assert entity.info == info_text


def test_create_synthesis_special_name():
    """特殊字符名: name="慕容复", 验证 id 格式正确。"""
    entity = create_synthesis_entity(
        name="慕容复",
        info="人物小传内容",
        volumes_covered=[0, 1],
        source_profiles=[
            "C_慕容复__T_main_vol_0",
            "C_慕容复__T_main_vol_1",
        ],
    )

    # id 格式 C_{name}__synthesis 对含中文/特殊字符同样适用
    assert entity.id == "C_慕容复__synthesis"
    assert entity.name == "慕容复"
    assert entity.type == "character"
    assert entity.coords == {"T": "synthesis", "C": "慕容复"}
    assert entity.base_info["volumes_count"] == 2


def test_create_synthesis_empty_volumes():
    """空卷列表: volumes_covered=[], 验证实体仍可创建。"""
    entity = create_synthesis_entity(
        name="莫凡",
        info="人物小传内容",
        volumes_covered=[],
        source_profiles=[],
    )

    # 实体仍可创建
    assert isinstance(entity, Entity)
    assert entity.id == "C_莫凡__synthesis"

    # volumes_count 为 0
    assert entity.base_info["volumes_count"] == 0
    assert entity.base_info["category"] == "synthesis"

    # detail_info 空列表
    assert entity.detail_info["volumes_covered"] == []
    assert entity.detail_info["source_profiles"] == []

    # coords / info 仍正确
    assert entity.coords == {"T": "synthesis", "C": "莫凡"}
    assert entity.info == "人物小传内容"
