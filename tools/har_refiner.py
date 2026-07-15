#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · HAR (Hallucination-Aware Refinement) 自洽校验工具

锚定: v0.4.1_plan_final.md §T-B1
功能: 对 Info 不达标的条目执行递归重抽（≤3 次），含预算上限和中止阈值。

核心逻辑:
1. 输入：schema_validator 校验失败的条目列表（info < 500 字或结构不达标）
2. 对每个条目，构造重抽 prompt（含原文 chunk 内容 + 四段格式要求 + 字数约束）
3. LLM 重抽（最多 max_retries 次），每次重抽后校验
4. max_retries 次仍不达标 → 写入 hint_tags=["HAR_FAILED"]，importance 降级为 low
5. 输出：修正后的条目列表 + 重抽统计

成本控制:
- 预算上限 budget_limit：达到后批次中止，剩余条目降级
- 中止阈值 failure_threshold：单批失败率 > 阈值即中止
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

try:
    from .models import get_info_schema, INFO_TOTAL_MIN, INFO_TOTAL_MAX
    from .schema_validator import (
        validate_info_length_v041,
        validate_info_structure,
    )
except ImportError:
    from models import get_info_schema, INFO_TOTAL_MIN, INFO_TOTAL_MAX
    from schema_validator import (
        validate_info_length_v041,
        validate_info_structure,
    )

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_FAILURE_THRESHOLD = 0.30
DEFAULT_BUDGET_MULTIPLIER = 2.9  # 96.3% × 3 次


def refine_info(
    entries: list[dict],
    chunks: dict[int, str],
    llm_client: Callable[[str], str],
    max_retries: int = DEFAULT_MAX_RETRIES,
    budget_limit: int | None = None,
    failure_threshold: float = DEFAULT_FAILURE_THRESHOLD,
) -> tuple[list[dict], dict]:
    """HAR 自洽校验重抽。

    Args:
        entries: 待校验的条目列表，每个条目为 dict 含 event_id/importance/delta_update
        chunks: chunk 索引 → 原文文本映射，用于构造重抽 prompt
        llm_client: LLM 调用函数，输入 prompt 返回 LLM 输出文本
        max_retries: 单条目最大重抽次数（默认 3）
        budget_limit: 最大 LLM 调用次数上限；None 表示按 2.9× 自动计算
        failure_threshold: 单批失败率中止阈值（默认 0.30）

    Returns:
        (修正后条目列表, 统计信息 dict)
        统计字段: total/success/failed/retries_avg/budget_used/aborted
    """
    # 自动计算预算
    if budget_limit is None:
        budget_limit = int(len(entries) * DEFAULT_BUDGET_MULTIPLIER)

    # 识别需要重抽的条目
    needs_refine: list[tuple[int, dict]] = []
    for idx, entry in enumerate(entries):
        info = _extract_info(entry)
        if not info:
            needs_refine.append((idx, entry))
            continue
        passed_len, _, _ = validate_info_length_v041(info)
        passed_struct, _ = validate_info_structure(info)
        if not (passed_len and passed_struct):
            needs_refine.append((idx, entry))

    stats = {
        "total": len(needs_refine),
        "success": 0,
        "failed": 0,
        "retries_avg": 0,
        "budget_used": 0,
        "aborted": False,
    }

    if not needs_refine:
        return entries, stats

    # 自动预算 = 待重抽条目数 × max_retries，但不超过 budget_limit
    auto_budget = min(len(needs_refine) * max_retries, budget_limit)

    call_count = 0
    total_retries = 0
    aborted = False

    for idx, entry in needs_refine:
        if aborted:
            # 中止后剩余条目直接降级
            _mark_har_failed(entry)
            stats["failed"] += 1
            continue

        success = False
        for retry in range(1, max_retries + 1):
            if call_count >= auto_budget:
                aborted = True
                break

            # 构造 prompt 并调用 LLM
            prompt = _build_refine_prompt(entry, chunks)
            try:
                new_info = llm_client(prompt)
            except Exception as exc:
                logger.warning(f"HAR LLM 调用失败 (event_id={entry.get('event_id', '?')}, retry={retry}): {exc}")
                call_count += 1
                total_retries += 1
                break  # 异常不重试，直接标记失败

            call_count += 1
            total_retries += 1

            if _is_info_valid(new_info):
                _update_info(entry, new_info)
                success = True
                break

        if not success:
            _mark_har_failed(entry)
            stats["failed"] += 1
            # 检查失败率阈值（最小样本量 3，避免单条目误触发）
            processed = stats["success"] + stats["failed"]
            if processed >= 3 and stats["failed"] / processed > failure_threshold:
                aborted = True
        else:
            stats["success"] += 1

    stats["retries_avg"] = total_retries / len(needs_refine) if needs_refine else 0
    stats["budget_used"] = call_count
    stats["aborted"] = aborted

    logger.info(
        f"HAR 重抽完成: total={stats['total']}, success={stats['success']}, "
        f"failed={stats['failed']}, retries_avg={stats['retries_avg']:.2f}, "
        f"budget_used={call_count}/{auto_budget}, aborted={aborted}"
    )

    return entries, stats


# ─── 内部辅助函数 ───────────────────────────────────────

def _extract_info(entry: dict) -> str:
    """从条目中提取 info 字段。"""
    try:
        return entry.get("delta_update", {}).get("updated_fields", {}).get("info", "") or ""
    except (AttributeError, TypeError):
        return ""


def _is_info_valid(info: str) -> bool:
    """检查 info 是否达标（字数 + 结构）。"""
    if not info:
        return False
    passed_len, _, _ = validate_info_length_v041(info)
    passed_struct, _ = validate_info_structure(info)
    return passed_len and passed_struct


def _update_info(entry: dict, new_info: str) -> None:
    """更新条目的 info 字段。"""
    entry.setdefault("delta_update", {}).setdefault("updated_fields", {})["info"] = new_info


def _mark_har_failed(entry: dict) -> None:
    """标记条目为 HAR_FAILED，并降级 importance。"""
    updated = entry.setdefault("delta_update", {}).setdefault("updated_fields", {})
    hint_tags = updated.get("hint_tags", [])
    if "HAR_FAILED" not in hint_tags:
        hint_tags.append("HAR_FAILED")
    updated["hint_tags"] = hint_tags
    entry["importance"] = "low"


def _build_refine_prompt(entry: dict, chunks: dict[int, str]) -> str:
    """构造 HAR 重抽 prompt。"""
    event_id = entry.get("event_id", "unknown")
    old_info = _extract_info(entry)

    # 提取 src:chunk 标记中的 chunk 索引
    chunk_indices: list[int] = []
    for match in re.finditer(r"\[src:chunk_(\d+)(?:-(\d+))?\]", old_info or ""):
        start = int(match.group(1))
        chunk_indices.append(start)
        if match.group(2):
            end = int(match.group(2))
            chunk_indices.extend(range(start, end + 1))

    # 去重排序
    chunk_indices = sorted(set(chunk_indices))

    # 获取原文 chunk 内容
    chunk_texts = []
    for idx in chunk_indices:
        if idx in chunks:
            chunk_texts.append(f"--- chunk_{idx} ---\n{chunks[idx]}")

    chunk_block = "\n\n".join(chunk_texts) if chunk_texts else "(无可用 chunk 原文)"

    return f"""你是严格的知识图谱语义抽取器。以下条目的 info 字段不达标，请基于原文重新抽取。

事件 ID: {event_id}
当前 info（不达标）:
{old_info or "(空)"}

原文 chunk:
{chunk_block}

重抽要求:
1. info 必须按四段结构输出，每段以段首标记开头:
   【起因】（≥100字）：事件触发的根本原因，包含背景上下文。[src:chunk_NNN]
   【经过】（≥200字）：核心过程概括，按时间顺序组织，含关键转折点。[src:chunk_NNN]
   【结果】（≥100字）：事件结局和对后续的影响。[src:chunk_NNN]
   【模块定位】（≥100字）：事件在所属剧情模块中的位置和作用。[src:chunk_NNN]
2. 总字数 500-1500 字
3. 每段末尾必须附加 [src:chunk_NNN] 标记
4. 必须是 LLM 语义提炼，禁止原文摘录拼凑

请直接输出新的 info 字段（不含解释文字，不含 Markdown 代码块标记）:
"""


def generate_har_prompt(
    entity_type: str,
    original_info: str,
    chunk_text: str,
) -> str:
    """按实体类型生成 HAR 重抽 prompt（v0.5.0 A2）。

    Args:
        entity_type: 实体类型（event/character/location/item/rule/system）
        original_info: 原始 info 文本
        chunk_text: 对应 chunk 的原文内容

    Returns:
        HAR 重抽用的完整 prompt 字符串
    """
    sections = get_info_schema(entity_type)
    if not sections:
        sections = get_info_schema("event")  # 回退到 event Schema

    total_min = INFO_TOTAL_MIN.get(entity_type, 500)
    total_max = INFO_TOTAL_MAX.get(entity_type, 1500)

    # 构建段结构说明
    section_lines = []
    for i, (name, min_chars) in enumerate(sections):
        if entity_type == "event":
            section_lines.append(f"   【{name}】（≥{min_chars}字）：... [src:chunk_NNN]")
        else:
            section_lines.append(f"   【{name}】（≥{min_chars}字）：...")

    section_block = "\n".join(section_lines)

    src_requirement = ""
    next_num = "3"
    if entity_type == "event":
        src_requirement = "\n3. 每段末尾必须附加 [src:chunk_NNN] 标记"
        next_num = "4"

    return f"""你是严格的知识图谱语义抽取器。以下条目的 info 字段不达标，请基于原文重新抽取。

当前 info（不达标）:
{original_info or "(空)"}

原文 chunk:
{chunk_text}

重抽要求:
1. info 必须按以下结构输出，每段以段首标记开头:
{section_block}
2. 总字数 {total_min}-{total_max} 字{src_requirement}
{next_num}. 必须是 LLM 语义提炼，禁止原文摘录拼凑

请直接输出新的 info 字段（不含解释文字，不含 Markdown 代码块标记）:
"""
