#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 坐标迁移工具

锚定: L3_接口契约与约束.md §1.1.3

旧六维多值坐标 (T/L/C/E/K/R) 迁移到新五维唯一值 (T/L/C/E/R)。
- T/L/C/E: 取列表第一个非空值作为唯一值
- K: 直接移除（主题由 E_module 承担）
- R: 从字典 {subtype: value} 转为子类字符串（取第一个非空子类的值）
- 缺失维度填充为空字符串
"""

from __future__ import annotations

import structlog

try:
    from .models import COORD_DIMENSIONS
    from .schema_validator import validate_coords_unique, validate_no_K_dimension
except ImportError:
    from models import COORD_DIMENSIONS
    from schema_validator import validate_coords_unique, validate_no_K_dimension

logger = structlog.get_logger(__name__)

# 需要从列表提取唯一值的维度 = COORD_DIMENSIONS 中除 R 外的维度
_MIGRATE_DIMS = tuple(dim for dim in COORD_DIMENSIONS if dim != "R")


def migrate_coords(old_coords: dict) -> dict:
    """旧六维多值坐标迁移到新五维唯一值。

    迁移规则：
    - T/L/C/E 维度：取列表第一个非空值作为唯一值
    - K 维度：直接移除（主题由 E_module 承担）
    - R 维度：从字典 {subtype: value} 转为字符串（取第一个非空子类的值）
    - 缺失维度填充为空字符串

    Args:
        old_coords: 旧六维坐标字典，形如::

            {T: [...], L: [...], C: [...], E: [...], K: [...], R: {subtype: value}}

    Returns:
        新五维坐标字典，形如::

            {T: str, L: str, C: str, E: str, R: str}

    Raises:
        KeyError: old_coords 既不含 T 也不含 L/C/E 任意一维
    """
    # 校验至少含 T/L/C/E 一维
    if not any(dim in old_coords for dim in _MIGRATE_DIMS):
        raise KeyError(
            f"old_coords 必须包含 T/L/C/E 至少一维，当前 keys={list(old_coords.keys())}"
        )

    new_coords: dict[str, str] = {}

    # T/L/C/E: 取列表第一个非空值
    for dim in _MIGRATE_DIMS:
        new_coords[dim] = _extract_first_non_empty(old_coords.get(dim))

    # R: 从字典转为字符串
    new_coords["R"] = _extract_r_value(old_coords.get("R"))

    # 仅保留五维坐标，过滤任何额外维度（如 K）
    new_coords = {dim: new_coords.get(dim, "") for dim in COORD_DIMENSIONS}

    # 交叉校验（T-A2 协同）
    if not validate_coords_unique(new_coords):
        logger.warning("迁移后坐标未通过 validate_coords_unique", new_coords=new_coords)
    if not validate_no_K_dimension(new_coords):
        logger.warning("迁移后坐标含 K 维度", new_coords=new_coords)

    logger.info(
        "坐标迁移完成",
        old_keys=list(old_coords.keys()),
        new_keys=list(new_coords.keys()),
    )
    return new_coords


def _extract_first_non_empty(value: object) -> str:
    """从列表或标量中提取第一个非空字符串值。

    支持旧格式中 T/L/C/E 维度为 list 或 str 的情况。

    Args:
        value: 列表、字符串或 None

    Returns:
        第一个非空字符串值；无则返回空字符串
    """
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item
            if item is not None and not isinstance(item, str):
                return str(item)
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _extract_r_value(r_value: object) -> str:
    """从 R 维度值中提取字符串。

    旧格式为字典 {subtype: value}，取第一个非空子类的值。
    若已是字符串则直接返回。

    Args:
        r_value: 字典、字符串或 None

    Returns:
        R 维度的字符串值；无则返回空字符串
    """
    if r_value is None:
        return ""
    if isinstance(r_value, dict):
        for v in r_value.values():
            if isinstance(v, str) and v.strip():
                return v
            if v is not None and not isinstance(v, str):
                return str(v)
        return ""
    if isinstance(r_value, str):
        return r_value
    return str(r_value)
