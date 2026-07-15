#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · Document Distiller（文档蒸馏器）

锚定: v0.4.1_plan_final.md §T-D1
功能: 对每个 chunk 执行 blueprint 重构，将原文蒸馏为结构化语义块。

Blueprint 模板:
    场景：[地点] [时间] [参与角色]
    行动：[核心事件描述]
    变动：[规则变动/角色弧光/关系变化]
    因果：[前因] → [后果]

降级开关:
    环境变量 NOVEL_ANALYSIS_SKIP_DISTILL=1 时跳过 distill，S3 直接使用原始 chunk。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

SKIP_ENV_VAR = "NOVEL_ANALYSIS_SKIP_DISTILL"

# Blueprint 字段名（中文）
_BLUEPRINT_FIELDS = ("场景", "行动", "变动", "因果")
_FIELD_MAP = {
    "场景": "scene",
    "行动": "action",
    "变动": "change",
    "因果": "causality",
}


def distill_chunk(
    chunk_text: str,
    llm_client: Callable[[str], str],
    chunk_index: int,
) -> dict[str, Any]:
    """对单个 chunk 执行 Document Distiller blueprint 重构。

    Args:
        chunk_text: 原始 chunk 文本
        llm_client: LLM 调用函数，输入 prompt 返回 LLM 输出文本
        chunk_index: chunk 索引（用于日志和缓存键）

    Returns:
        {
            "scene": str - 场景描述
            "action": str - 核心行动
            "change": str - 变动内容
            "causality": str - 因果关系
            "raw_summary": str - 原始摘要（= 四字段拼接或原始 chunk）
            "skipped": bool - 是否被降级跳过（仅 skip 时为 True）
            "chunk_index": int - chunk 索引
        }
    """
    # 降级开关检查
    if os.environ.get(SKIP_ENV_VAR, "").strip() in ("1", "true", "True", "yes"):
        logger.info(f"Distiller 被降级跳过 (chunk_index={chunk_index})")
        return {
            "scene": "",
            "action": "",
            "change": "",
            "causality": "",
            "raw_summary": chunk_text,
            "skipped": True,
            "chunk_index": chunk_index,
        }

    # 构造 prompt 并调用 LLM
    prompt = _build_distill_prompt(chunk_text, chunk_index)
    try:
        llm_output = llm_client(prompt)
    except Exception as exc:
        logger.warning(f"Distiller LLM 调用失败 (chunk_index={chunk_index}): {exc}")
        return {
            "scene": "",
            "action": "",
            "change": "",
            "causality": "",
            "raw_summary": chunk_text,
            "skipped": False,
            "chunk_index": chunk_index,
            "error": str(exc),
        }

    # 解析 Blueprint
    blueprint = _parse_blueprint(llm_output)

    # 拼接 raw_summary
    raw_summary = "\n".join(
        f"{cn}：{blueprint[en]}" for cn, en in zip(_BLUEPRINT_FIELDS, ("scene", "action", "change", "causality"))
    )

    return {
        "scene": blueprint["scene"],
        "action": blueprint["action"],
        "change": blueprint["change"],
        "causality": blueprint["causality"],
        "raw_summary": raw_summary,
        "skipped": False,
        "chunk_index": chunk_index,
    }


def _parse_blueprint(text: str) -> dict[str, str]:
    """解析 LLM 输出的 Blueprint 文本。

    Args:
        text: LLM 输出文本，格式为:
            场景：xxx
            行动：xxx
            变动：xxx
            因果：xxx

    Returns:
        {"scene": str, "action": str, "change": str, "causality": str}
        缺失字段为空字符串
    """
    result = {"scene": "", "action": "", "change": "", "causality": ""}

    if not text or not isinstance(text, str):
        return result

    # 按行解析
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # 匹配 "字段名：值" 或 "字段名:值"
        for cn_field, en_field in _FIELD_MAP.items():
            prefix = f"{cn_field}："
            prefix_alt = f"{cn_field}:"
            if line.startswith(prefix):
                result[en_field] = line[len(prefix):].strip()
                break
            if line.startswith(prefix_alt):
                result[en_field] = line[len(prefix_alt):].strip()
                break

    return result


def _build_distill_prompt(chunk_text: str, chunk_index: int) -> str:
    """构造 Document Distiller prompt。"""
    return f"""你是严格的文本蒸馏器。请将以下小说原文重构为结构化 Blueprint 语义块。

原文 chunk (index={chunk_index}):
{chunk_text}

输出要求:
1. 必须按以下 Blueprint 模板输出，每行一个字段
2. 每个字段以 "字段名：值" 格式输出（中文冒号）
3. 总字数 150-400 字
4. 必须是 LLM 语义提炼，禁止原文摘录

Blueprint 模板:
场景：[地点] [时间] [参与角色]
行动：[核心事件描述]
变动：[规则变动/角色弧光/关系变化]
因果：[前因] → [后果]

请直接输出 Blueprint（不含解释文字，不含 Markdown 代码块标记）:
"""
