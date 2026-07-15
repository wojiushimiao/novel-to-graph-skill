#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · Schema 校验器

锚定: L2_数据模型与核心算法.md §2.5
      L3_接口契约与约束.md §1.2.2

校验 JSON 字典是否符合 LLM 输出 Schema。
校验失败的记录丢弃并记录警告日志。
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from .models import (
        IMPORTANCE_LEVELS,
        RELATION_TYPES,
        R_SUBTYPES,
        LEGACY_TO_AXIS_MAP,
        SchemaValidationError,
        Entity,
        COORD_DIMENSIONS,
        get_info_schema,
    )
except ImportError:
    from models import (
        IMPORTANCE_LEVELS,
        RELATION_TYPES,
        R_SUBTYPES,
        LEGACY_TO_AXIS_MAP,
        SchemaValidationError,
        Entity,
        COORD_DIMENSIONS,
        get_info_schema,
    )

# 允许的关系类型：新轴关系类型 + 旧关系类型（由 S6.1 负责转换为轴关系类型）
_ALLOWED_RELATION_TYPES = set(RELATION_TYPES) | set(LEGACY_TO_AXIS_MAP.keys())

logger = logging.getLogger(__name__)

# 必填顶层字段
_REQUIRED_FIELDS = ("event_id", "stitch", "coords", "importance", "delta_update")

# stitch 必填子字段
_REQUIRED_STITCH = ("sigma", "epsilon", "kappa")

# coords 必填子字段（v0.4.0: 五维，移除 K）
_REQUIRED_COORDS = ("T", "L", "C", "E", "R")

# delta_update 必填子字段
_REQUIRED_DELTA = ("target_entity_id", "updated_fields")

# delta_update.updated_fields 必填子字段
_REQUIRED_UPDATED_FIELDS = ("info", "new_wiki_relations")


def validate(items: list[dict]) -> list[dict]:
    """校验 JSON 字典列表是否符合 Schema。

    校验项：
    - 必填字段存在性: event_id, stitch, coords, importance, delta_update
    - 类型合法性: importance 必须 ∈ {high, medium, low}
    - 枚举值合法性: relation_type 必须 ∈ 7种；R.subtype 必须 ∈ 6种
    - 嵌套结构合法性: delta_update.updated_fields.new_wiki_relations 必须是数组

    Args:
        items: 待校验字典列表

    Returns:
        通过校验的字典列表（校验失败的丢弃+警告日志）
    """
    result: list[dict] = []
    for idx, item in enumerate(items):
        try:
            _validate_one(item)
            result.append(item)
        except SchemaValidationError as exc:
            logger.warning(f"Schema 校验失败 #{idx} (event_id={item.get('event_id', '?')}): {exc}")

    logger.info(f"Schema 校验完成: {len(result)}/{len(items)} 条通过")
    return result


def _validate_one(item: dict[str, Any]) -> None:
    """校验单个字典。失败抛 SchemaValidationError。"""
    if not isinstance(item, dict):
        raise SchemaValidationError(f"顶层非 dict: {type(item).__name__}")

    # 必填字段
    for field in _REQUIRED_FIELDS:
        if field not in item:
            raise SchemaValidationError(f"缺失必填字段: {field}")

    # event_id
    if not isinstance(item["event_id"], str) or not item["event_id"].strip():
        raise SchemaValidationError("event_id 必须为非空字符串")

    # stitch
    stitch = item["stitch"]
    if not isinstance(stitch, dict):
        raise SchemaValidationError("stitch 必须为 dict")
    for f in _REQUIRED_STITCH:
        if f not in stitch or not isinstance(stitch[f], str) or not stitch[f].strip():
            raise SchemaValidationError(f"stitch.{f} 必须为非空字符串")

    # coords（v0.4.0: 五维 T/L/C/E/R，移除 K；R 可为字符串或 dict）
    coords = item["coords"]
    if not isinstance(coords, dict):
        raise SchemaValidationError("coords 必须为 dict")
    for f in _REQUIRED_COORDS:
        if f not in coords:
            raise SchemaValidationError(f"coords.{f} 缺失")
    # T/L/C/E 可以是字符串(v0.4.0)或列表(v0.3.0遗留)，但必须存在
    for f in ("T", "L", "C", "E"):
        v = coords.get(f)
        if v is None:
            continue
        if not isinstance(v, (str, list)):
            raise SchemaValidationError(f"coords.{f} 必须为字符串或列表")
    # R 兼容 v0.4.0（字符串）和 v0.3.0（dict）
    r_val = coords.get("R")
    if isinstance(r_val, dict):
        # v0.3.0 遗留格式：{subtype, rule_name}
        r_subtype = r_val.get("subtype")
        if r_subtype and r_subtype not in R_SUBTYPES:
            raise SchemaValidationError(
                f"coords.R.subtype 非法: {r_subtype}; 合法值: {R_SUBTYPES}"
            )
    elif isinstance(r_val, str):
        # v0.4.0 格式：字符串子类前缀，如 "R_power"
        pass
    elif r_val is not None:
        raise SchemaValidationError(f"coords.R 类型非法: {type(r_val).__name__}")

    # importance
    importance = item["importance"]
    if importance not in IMPORTANCE_LEVELS:
        raise SchemaValidationError(
            f"importance 非法: {importance}; 合法值: {IMPORTANCE_LEVELS}"
        )

    # delta_update
    delta = item["delta_update"]
    if not isinstance(delta, dict):
        raise SchemaValidationError("delta_update 必须为 dict")
    for f in _REQUIRED_DELTA:
        if f not in delta:
            raise SchemaValidationError(f"delta_update.{f} 缺失")
    if not isinstance(delta["target_entity_id"], str) or not delta["target_entity_id"].strip():
        raise SchemaValidationError("delta_update.target_entity_id 必须为非空字符串")

    updated = delta["updated_fields"]
    if not isinstance(updated, dict):
        raise SchemaValidationError("delta_update.updated_fields 必须为 dict")
    for f in _REQUIRED_UPDATED_FIELDS:
        if f not in updated:
            raise SchemaValidationError(f"delta_update.updated_fields.{f} 缺失")
    if not isinstance(updated["info"], str) or not updated["info"].strip():
        raise SchemaValidationError("delta_update.updated_fields.info 必须为非空字符串")
    if not isinstance(updated["new_wiki_relations"], list):
        raise SchemaValidationError("delta_update.updated_fields.new_wiki_relations 必须为列表")

    # 校验关系类型（允许新轴关系类型 + 旧关系类型，旧类型由 S6.1 转换）
    for rel in updated["new_wiki_relations"]:
        if not isinstance(rel, dict):
            raise SchemaValidationError(f"new_wiki_relations 元素非 dict: {rel}")
        rel_type = rel.get("type")
        if rel_type and rel_type not in _ALLOWED_RELATION_TYPES:
            raise SchemaValidationError(
                f"new_wiki_relations[].type 非法: {rel_type}; 合法值: {_ALLOWED_RELATION_TYPES}"
            )
        strength = rel.get("strength", "weak")
        if strength not in ("strong", "weak"):
            raise SchemaValidationError(f"new_wiki_relations[].strength 非法: {strength}")

    # conflict_detected 必填且为布尔
    if "conflict_detected" not in delta:
        raise SchemaValidationError("delta_update.conflict_detected 缺失")
    if not isinstance(delta["conflict_detected"], bool):
        raise SchemaValidationError("delta_update.conflict_detected 必须为布尔")

    # conflict_note（若 conflict_detected=True 必须有说明）
    if delta["conflict_detected"]:
        note = delta.get("conflict_note", "")
        if not isinstance(note, str) or not note.strip():
            raise SchemaValidationError("conflict_detected=True 时 conflict_note 不能为空")


# ============================================================
# v0.4.0 校验函数（7 个新增）
# 锚定: L3_接口契约与约束.md §3.1~§3.4
# ============================================================

def validate_coords_unique(coords: dict) -> bool:
    """校验五维坐标每维度为唯一值（str 而非 list）。

    v0.4.0 坐标-关系分离原则：坐标=位置（唯一值），关系=连接（多值边）。
    每维度仅含一个 string 值，不允许列表。

    Args:
        coords: 坐标字典，形如 {"T": str, "L": str, "C": str, "E": str, "R": str}

    Returns:
        True=通过（所有维度为 str 或空字符串），False=拒绝（存在 list 值）
    """
    if not isinstance(coords, dict):
        return False
    for dim in COORD_DIMENSIONS:
        v = coords.get(dim)
        if v is None:
            continue
        if isinstance(v, list):
            return False
        if not isinstance(v, str):
            return False
    return True


def validate_no_K_dimension(coords: dict) -> bool:
    """校验 coords 字典的 keys 不含 'K' 维度。

    v0.4.0 移除 K 维度，由 E_module 剧情模块替代。

    Args:
        coords: 坐标字典

    Returns:
        True=通过（无 K 维度），False=拒绝（含 K 维度）
    """
    if not isinstance(coords, dict):
        return False
    return "K" not in coords


def validate_info_length(info: str) -> tuple[bool, str]:
    """校验 info 字数范围。

    v0.4.0 info 质量强化：500-1500 字 LLM 语义提炼。

    Args:
        info: 实体详情文本

    Returns:
        (True, "pass"): 字数 ∈ [500, 1500]，通过
        (False, "too_short"): 字数 < 500，拒绝
        (False, "trigger_compress"): 字数 > 1500，触发压缩
    """
    if not isinstance(info, str):
        return False, "invalid_type"
    length = len(info)
    if length < 500:
        return False, "too_short"
    if length > 1500:
        return False, "trigger_compress"
    return True, "pass"


def validate_E_module_relation(entities: list, relations: list) -> bool:
    """校验 T_main 仅连接 E_module→E_module。

    v0.4.0 T类语义重构：T_main 为纯索引（模块间），不允许连接其他类型。

    Args:
        entities: Entity 列表，用于查找实体类型
        relations: Relation 列表，检查 T_main 关系

    Returns:
        True=通过（所有 T_main 关系均连接 E_module→E_module 或无 T_main 关系）
    """
    if not relations:
        return True
    # 构建实体 ID → 类型映射
    entity_type_map: dict[str, str] = {}
    for ent in entities:
        if hasattr(ent, "id") and hasattr(ent, "type"):
            entity_type_map[ent.id] = ent.type
        elif isinstance(ent, dict):
            entity_type_map[ent.get("id", "")] = ent.get("type", "")

    for rel in relations:
        rel_type = rel.relation_type if hasattr(rel, "relation_type") else rel.get("relation_type", "")
        if rel_type != "T_main":
            continue
        src_id = rel.source_id if hasattr(rel, "source_id") else rel.get("source_id", "")
        tgt_id = rel.target_id if hasattr(rel, "target_id") else rel.get("target_id", "")
        src_type = entity_type_map.get(src_id, "")
        tgt_type = entity_type_map.get(tgt_id, "")
        if src_type != "E_module" or tgt_type != "E_module":
            return False
    return True


def validate_relation_desc_length(description: str) -> tuple[bool, str]:
    """校验关系 description 字数。

    v0.4.0 微调：关系边是"指针+门控"，不是"内容容器"。
    - ≤50 字：推荐，通过
    - 50-100 字：标记疑似详情分散
    - >100 字：拒绝入库

    Args:
        description: 关系描述文本

    Returns:
        (True, "pass"): 字数 ≤50，符合推荐
        (True, "warn_suspicious"): 字数 ∈ (50, 100]，标记疑似详情分散
        (False, "reject_too_long"): 字数 > 100，拒绝入库
    """
    if not isinstance(description, str):
        return False, "invalid_type"
    length = len(description)
    if length > 100:
        return False, "reject_too_long"
    if length > 50:
        return True, "warn_suspicious"
    return True, "pass"


def validate_info_cohesion(entity: Entity, out_relations: list) -> tuple[bool, str]:
    """校验节点详情是否内聚于 info 字段（防止详情分散到关系边）。

    v0.4.0 微调信息架构原则：
    - 实体 info 字数 < 500 且 出边数 ≥3：标记疑似详情分散
    - 任一出边 description > 100 字：拒绝入库（详情分散到关系边）
    - 任一出边 description ∈ (50, 100]：标记疑似分散

    Args:
        entity: 待校验实体（需有 info 字段）
        out_relations: 该实体的出边列表

    Returns:
        (True, "pass"): 通过
        (True, "warn_suspicious"): 标记疑似分散
        (False, "reject_desc_too_long"): 拒绝（出边 description 超长）
        (False, "reject_info_not_cohesive"): 拒绝（info 过短且出边过多）
    """
    # 获取 info 字数
    info_text = getattr(entity, "info", "") if not isinstance(entity, dict) else entity.get("info", "")
    info_len = len(info_text) if isinstance(info_text, str) else 0
    out_count = len(out_relations) if out_relations else 0

    # 检查出边 description 长度
    has_overlong_desc = False
    has_suspicious_desc = False
    for rel in out_relations or []:
        desc = rel.description if hasattr(rel, "description") else rel.get("description", "")
        if not isinstance(desc, str):
            continue
        desc_len = len(desc)
        if desc_len > 100:
            has_overlong_desc = True
        elif desc_len > 50:
            has_suspicious_desc = True

    # 拒绝级：出边 description > 100 字
    if has_overlong_desc:
        return False, "reject_desc_too_long"

    # 警告级：出边 description 50-100 字 或 info 过短+出边过多
    if has_suspicious_desc:
        return True, "warn_suspicious"
    if info_len < 500 and out_count >= 3:
        return True, "warn_suspicious"

    return True, "pass"


def validate_S_topo_bidirectional(relations: list) -> bool:
    """校验 S_topo 关系存在双向（实体→L + L→E_module/E_event）。

    v0.4.0 微调：S_topo 从辅轴提升为平行主轴，允许双向：
    - L6入边（实体→L）：实体地理归属
    - L7出边（L→E_module/E_event）：空间索引

    校验规则：若存在 S_topo 关系，必须有入边和出边同时存在（双向）。
    若无 S_topo 关系，视为通过（不强制要求存在）。

    Args:
        relations: 关系列表（dict 或 Relation 对象）

    Returns:
        True=通过（无 S_topo 或双向完整），False=拒绝（仅单向）
    """
    if not relations:
        return True

    # 收集所有 S_topo 关系的 source_id 和 target_id
    s_topo_sources: set[str] = set()
    s_topo_targets: set[str] = set()
    has_s_topo = False

    for rel in relations:
        rel_type = rel.relation_type if hasattr(rel, "relation_type") else rel.get("relation_type", "")
        if rel_type != "S_topo":
            continue
        has_s_topo = True
        src_id = rel.source_id if hasattr(rel, "source_id") else rel.get("source_id", "")
        tgt_id = rel.target_id if hasattr(rel, "target_id") else rel.get("target_id", "")
        s_topo_sources.add(src_id)
        s_topo_targets.add(tgt_id)

    if not has_s_topo:
        return True

    # 双向校验：target 集合中应有元素同时出现在 source 集合中
    # 即存在某个 L，既是某个 S_topo 的 target（实体→L），又是某个 S_topo 的 source（L→E_module/E_event）
    bidirectional_nodes = s_topo_targets & s_topo_sources
    return len(bidirectional_nodes) > 0


# ============================================================
# v0.4.1 HAR 接口扩展
# 锚定: v0.4.1_plan_final.md §T-B2
# ============================================================

import re as _re

# 合法 [src:chunk_NNN] 或 [src:chunk_NNN-MMM] 标记正则
_SRC_MARKER_PATTERN = _re.compile(r"\[src:chunk_(\d+)(?:-(\d+))?\]")


def validate_info_structure(info: str, entity_type: str = "event") -> tuple[bool, str]:
    """校验 info 结构完整性（v0.5.0: 按实体类型选择 Schema）。

    Args:
        info: 实体详情文本
        entity_type: 实体类型（默认 "event" 向后兼容）

    Returns:
        (True, "pass"): 结构完整且字数达标
        (False, "missing_section: <name>"): 缺失某段
        (False, "section_too_short: <name>"): 某段字数不足
    """
    if not isinstance(info, str) or not info:
        return False, "missing_section: 起因"

    # v0.5.0 A2: 按 entity_type 选取 Schema
    sections = get_info_schema(entity_type)
    if not sections:
        # 未知类型不校验
        return True, "pass"

    for section_name, min_chars in sections:
        marker = f"【{section_name}】"
        idx = info.find(marker)
        if idx < 0:
            return False, f"missing_section: {section_name}"

        # 段内容 = 从段首标记后到下一个段首标记（或字符串末尾）
        start = idx + len(marker)
        next_idx = len(info)
        for other_name, _ in sections:
            if other_name == section_name:
                continue
            other_marker = f"【{other_name}】"
            other_idx = info.find(other_marker, start)
            if other_idx >= 0 and other_idx < next_idx:
                next_idx = other_idx

        section_text = info[start:next_idx]
        # 剥离 src 标记后计字数
        section_text_clean = _SRC_MARKER_PATTERN.sub("", section_text).strip()
        if len(section_text_clean) < min_chars:
            return False, f"section_too_short: {section_name}"

    return True, "pass"


def validate_src_marker(info: str) -> tuple[bool, str]:
    """校验 info 每段末尾的 [src:chunk_NNN] 标记。

    v0.4.1 过程校验：每段必须含合法 [src:chunk_NNN] 或 [src:chunk_NNN-MMM] 标记。
    畸形标记（如 [src:chunk_abc]、[src:chunk_]）视为缺失。

    Args:
        info: 实体详情文本

    Returns:
        (True, "pass"): 所有段均含合法标记
        (False, "missing_marker: <section_name>"): 某段缺失标记
        (False, "malformed_marker: <marker>"): 标记格式畸形
    """
    if not isinstance(info, str) or not info:
        return False, "missing_marker: 起因"

    # 先检测畸形标记
    malformed_pattern = _re.compile(r"\[src:chunk_([^\]]*)\]")
    for match in malformed_pattern.finditer(info):
        inner = match.group(1)
        if not inner:
            return False, f"malformed_marker: {match.group(0)}"
        if not _re.match(r"^\d+(?:-\d+)?$", inner):
            return False, f"malformed_marker: {match.group(0)}"

    # v0.5.0: 从 INFO_SCHEMA 获取 event 类型的段定义（替代旧 _INFO_SECTIONS）
    sections = get_info_schema("event")
    if not sections:
        return True, "pass"

    # 检测每段是否含合法标记
    for section_name, _ in sections:
        marker = f"【{section_name}】"
        idx = info.find(marker)
        if idx < 0:
            return False, f"missing_marker: {section_name}"

        start = idx + len(marker)
        next_idx = len(info)
        for other_name, _ in sections:
            if other_name == section_name:
                continue
            other_marker = f"【{other_name}】"
            other_idx = info.find(other_marker, start)
            if other_idx >= 0 and other_idx < next_idx:
                next_idx = other_idx

        section_text = info[start:next_idx]
        if not _SRC_MARKER_PATTERN.search(section_text):
            return False, f"missing_marker: {section_name}"

    return True, "pass"


def strip_src_markers(info: str) -> str:
    """剥离 info 中的 [src:chunk_NNN] 过程校验标记。

    v0.4.1 S5 入库前强制调用。仅剥离合法标记（含跨 chunk 范围），
    畸形标记保留以供调试。

    Args:
        info: 含过程校验标记的文本

    Returns:
        剥离标记后的文本（畸形标记保留）
    """
    if not isinstance(info, str):
        return info
    return _SRC_MARKER_PATTERN.sub("", info)


def validate_info_length_v041(info: str) -> tuple[bool, str, dict]:
    """v0.4.1 扩展的 info 字数校验，返回 HAR 元数据。

    Args:
        info: 实体详情文本

    Returns:
        (True, "pass", meta): 字数 ∈ [500, 1500]
        (False, "too_short", meta): 字数 < 500，meta["needs_har"]=True
        (False, "trigger_compress", meta): 字数 > 1500，meta["needs_compress"]=True

        meta 字段:
            length: int - info 字数
            needs_har: bool - 是否需要 HAR 重抽
            needs_compress: bool - 是否需要压缩
    """
    if not isinstance(info, str):
        return False, "invalid_type", {"length": 0, "needs_har": False, "needs_compress": False}

    length = len(info)
    meta = {
        "length": length,
        "needs_har": False,
        "needs_compress": False,
    }

    if length < 500:
        meta["needs_har"] = True
        return False, "too_short", meta
    if length > 1500:
        meta["needs_compress"] = True
        return False, "trigger_compress", meta
    return True, "pass", meta

