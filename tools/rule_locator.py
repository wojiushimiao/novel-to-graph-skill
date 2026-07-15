#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 规则定位器

锚定: L2_数据模型与核心算法.md §2.2
      L3_接口契约与约束.md §1.1.4

基于正则规则扫描文本块，输出候选实体名称列表字符串，辅助 LLM 聚焦注意力。
**仅输出候选名称列表**，不生成 Entity 对象（实体抽取由 LLM 完成）。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Chunk

logger = logging.getLogger(__name__)

# 默认实体定位模式（基于 L2 §2.2 算法详述）
_DEFAULT_PATTERNS: dict[str, list[str]] = {
    # 角色候选：中文姓名（百家姓 + 1-2字）
    "character": [
        r"[李王张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯]"
        r"[\u4e00-\u9fff]{1,2}"
    ],
    # 地点候选：地名后缀模式
    "location": [
        r"[\u4e00-\u9fff]{2,4}(?:城|市|镇|村|山|河|海|湖|岛|谷|原|森林|沙漠|学院|公会|帝国|王国|联盟|圣地|秘境|禁地|域)"
    ],
    # 事件候选：事件后缀模式
    "event": [
        r"[\u4e00-\u9fff]{2,6}(?:之战|之役|大会|试炼|考核|觉醒|仪式|灾难|兽潮|战争|比赛|联盟|契约)"
    ],
    # 物品候选：物品后缀模式
    "item": [
        r"[\u4e00-\u9fff]{2,4}(?:剑|刀|枪|弓|杖|盾|甲|袍|戒|珠|石|玉|符|印|鼎|炉|丹|药|书|卷|器|宝)"
    ],
}

# 中文标签映射
_LABEL_MAP = {
    "character": "角色",
    "location": "地点",
    "event": "事件",
    "item": "物品",
}


def locate(
    chunks: "list[Chunk]",
    entity_patterns: dict[str, list[str]] | None = None,
) -> dict[int, str]:
    """基于规则扫描文本块，输出候选实体聚焦上下文。

    对每个 Chunk，使用预编译正则匹配候选实体名称，去重后输出
    格式化字符串供 LLM 参考。仅做候选定位，不构造 Entity 对象。

    Args:
        chunks: 文本块列表
        entity_patterns: 自定义模式 {类型: [正则字符串, ...]}，
                        None 时使用默认模式

    Returns:
        {chunk_index: "本章可能涉及的角色: [A, B]; 地点: [...]; 事件: [...]; 物品: [...]"}
    """
    patterns = entity_patterns or _DEFAULT_PATTERNS

    # 预编译正则
    compiled: dict[str, list[re.Pattern]] = {}
    for etype, regex_list in patterns.items():
        compiled[etype] = [re.compile(p, re.UNICODE) for p in regex_list]

    result: dict[int, str] = {}

    for chunk in chunks:
        text = chunk.content
        parts: list[str] = []

        for etype, regexes in compiled.items():
            candidates: list[str] = []
            seen: set[str] = set()
            for regex in regexes:
                for match in regex.finditer(text):
                    name = match.group(0)
                    if name not in seen:
                        seen.add(name)
                        candidates.append(name)
            if candidates:
                label = _LABEL_MAP.get(etype, etype)
                # 限制输出长度，避免超长候选列表
                if len(candidates) > 30:
                    candidates = candidates[:30]
                parts.append(f"{label}: [{', '.join(candidates)}]")

        if parts:
            result[chunk.index] = f"本章可能涉及的: " + "; ".join(parts)
        else:
            result[chunk.index] = "本章未检测到明显候选实体"

    logger.debug(f"规则定位完成: {len(result)} 个块的候选实体已输出")
    return result


def locate_in_text(
    text: str,
    entity_patterns: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """对单段文本进行候选实体定位。

    Args:
        text: 文本内容
        entity_patterns: 自定义模式

    Returns:
        {entity_type: [candidate_name, ...]}
    """
    patterns = entity_patterns or _DEFAULT_PATTERNS
    compiled = {
        etype: [re.compile(p, re.UNICODE) for p in regex_list]
        for etype, regex_list in patterns.items()
    }

    result: dict[str, list[str]] = {}
    for etype, regexes in compiled.items():
        seen: set[str] = set()
        candidates: list[str] = []
        for regex in regexes:
            for match in regex.finditer(text):
                name = match.group(0)
                if name not in seen:
                    seen.add(name)
                    candidates.append(name)
        if candidates:
            result[etype] = candidates[:30]

    return result
