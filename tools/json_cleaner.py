#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · JSON 清洗器

锚定: L2_数据模型与核心算法.md §2.4
      L3_接口契约与约束.md §1.2.1

从 LLM 原始输出字符串列表中提取合法 JSON 字典。
解析失败的记录丢弃并记录警告日志。
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Markdown 代码块标记（```json ... ``` 或 ``` ... ```）
_CODEBLOCK_PATTERN = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)\n?```",
    re.DOTALL,
)

# 单个 JSON 对象（贪婪匹配最外层 { ... }）
_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def extract(raw_outputs: list[str]) -> list[dict]:
    """从 LLM 原始输出中提取合法 JSON 字典。

    处理步骤：
    1. 去除 Markdown 代码块标记
    2. 提取纯 JSON 字符串
    3. 解析为 Python 字典
    4. 解析失败的记录丢弃并记录警告日志

    Args:
        raw_outputs: LLM 原始输出字符串列表

    Returns:
        合法 JSON 字典列表（保持原序，解析失败的丢弃）
    """
    result: list[dict] = []

    for idx, raw in enumerate(raw_outputs):
        if not raw or not raw.strip():
            logger.debug(f"输出 #{idx} 为空，跳过")
            continue

        cleaned = _strip_markdown(raw)
        json_str = _extract_json_object(cleaned)

        if json_str is None:
            logger.warning(f"输出 #{idx} 未找到 JSON 对象，丢弃")
            continue

        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError as exc:
            # 尝试修复常见转义问题后重试
            fixed = _fix_common_json_errors(json_str)
            try:
                obj = json.loads(fixed)
            except json.JSONDecodeError as exc2:
                logger.warning(
                    f"输出 #{idx} JSON 解析失败: {exc2}; 原始片段: {json_str[:120]}..."
                )
                continue

        if isinstance(obj, dict):
            result.append(obj)
        elif isinstance(obj, list):
            # LLM 可能返回数组
            for item in obj:
                if isinstance(item, dict):
                    result.append(item)
        else:
            logger.warning(f"输出 #{idx} 顶层不是对象或数组: {type(obj).__name__}")

    logger.info(f"JSON 清洗完成: {len(result)}/{len(raw_outputs)} 条有效")
    return result


def _strip_markdown(text: str) -> str:
    """去除 Markdown 代码块标记。

    Args:
        text: 原始字符串

    Returns:
        去除 ```json ... ``` 包裹后的字符串
    """
    match = _CODEBLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_json_object(text: str) -> str | None:
    """提取最外层 JSON 对象字符串。

    使用花括号计数法找到最外层的 { ... }。

    Args:
        text: 已去除 Markdown 标记的字符串

    Returns:
        JSON 字符串，或 None（未找到）
    """
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def _fix_common_json_errors(text: str) -> str:
    """修复常见的 JSON 转义错误。

    处理：
    - 中文引号 → 英文引号
    - 单引号 → 双引号（仅在键位置）
    - 尾随逗号去除

    Args:
        text: 原始 JSON 字符串

    Returns:
        修复后的 JSON 字符串
    """
    # 中文引号替换
    fixed = text.replace("\u201c", '"').replace("\u201d", '"')
    fixed = fixed.replace("\u2018", "'").replace("\u2019", "'")
    # 尾随逗号（对象和数组末尾）
    fixed = re.sub(r",\s*}", "}", fixed)
    fixed = re.sub(r",\s*\]", "]", fixed)
    return fixed
