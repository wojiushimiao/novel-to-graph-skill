#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · info字段压缩工具

锚定: L3_接口契约与约束.md §1.1.4
      track_C_plan.md §T-C2

info 字段超长（>1500字）时触发压缩流程。本工具遵循 skill 不调用 LLM 的
设计原则，仅负责触发（返回提示词模板）和校验（字数范围校验 + 重试 + 截断
兜底），实际压缩由宿主 AGENT 调用 LLM 完成。

字数统计规则: 按字符数统计 (len(text))，含标点、空格。
"""

from __future__ import annotations

from typing import Callable

import structlog

try:
    from .models import InfoCompressionError
except ImportError:
    from models import InfoCompressionError

logger = structlog.get_logger(__name__)

# 压缩触发阈值：info 字数超过此值才需压缩
COMPRESS_THRESHOLD = 1500

# 默认压缩目标范围
DEFAULT_TARGET_MIN = 1200
DEFAULT_TARGET_MAX = 1500

# 最大重试次数
MAX_RETRIES = 2


class InfoTooShortError(InfoCompressionError):
    """info 压缩后字数 < target_min（压缩过度）。

    对应错误码 E_INFO_TOO_SHORT，需人工介入或重新触发。
    """


def get_compress_prompt(
    info: str,
    target_min: int = DEFAULT_TARGET_MIN,
    target_max: int = DEFAULT_TARGET_MAX,
) -> str:
    """获取压缩提示词模板（供宿主 AGENT 调用 LLM 使用）。

    Args:
        info: 原始 info 文本
        target_min: 目标最小字数
        target_max: 目标最大字数

    Returns:
        压缩提示词模板字符串
    """
    return (
        f"将以下内容压缩至 {target_min}-{target_max} 字，"
        f"保留核心事实，去除冗余描述：\n\n{info}"
    )


def validate_compressed_info(
    compressed: str,
    target_min: int = DEFAULT_TARGET_MIN,
    target_max: int = DEFAULT_TARGET_MAX,
) -> tuple[bool, str]:
    """校验压缩后的 info 字数是否在目标范围。

    字数统计规则: 按字符数统计 (len(compressed))。

    Args:
        compressed: 压缩后的 info 文本
        target_min: 目标最小字数
        target_max: 目标最大字数

    Returns:
        (是否通过, 处理动作描述):
        - (True, "pass"): 字数 ∈ [target_min, target_max]
        - (False, "too_short"): 字数 < target_min
        - (False, "too_long"): 字数 > target_max
    """
    length = len(compressed)
    if length < target_min:
        return (False, "too_short")
    if length > target_max:
        return (False, "too_long")
    return (True, "pass")


def get_retry_prompt(
    original_info: str,
    compressed_info: str,
    target_min: int,
    target_max: int,
) -> str:
    """获取重试提示词（压缩结果不达标时）。

    Args:
        original_info: 原始 info 文本
        compressed_info: 上次压缩结果（不达标）
        target_min: 目标最小字数
        target_max: 目标最大字数

    Returns:
        重试提示词字符串
    """
    return (
        f"上次压缩结果字数为 {len(compressed_info)}，"
        f"不在目标范围 [{target_min}, {target_max}] 内。"
        f"请重新压缩以下原始内容至 {target_min}-{target_max} 字：\n\n{original_info}"
    )


def truncate_info(info: str, target_max: int = DEFAULT_TARGET_MAX) -> str:
    """截断兜底：重试 2 次仍失败时使用。

    按字符数截断到 target_max 字，并输出警告日志。

    Args:
        info: 待截断的文本
        target_max: 截断目标长度

    Returns:
        截断后的文本（长度 ≤ target_max）
    """
    if len(info) <= target_max:
        return info
    truncated = info[:target_max]
    logger.warning(
        "info 截断兜底",
        original_length=len(info),
        truncated_length=target_max,
    )
    return truncated


def compress_info(
    info: str,
    target_min: int = DEFAULT_TARGET_MIN,
    target_max: int = DEFAULT_TARGET_MAX,
) -> str:
    """压缩 info 字段到目标范围（触发函数）。

    Note: 实际压缩由 LLM 完成，此函数仅触发和校验。skill 不调用 LLM，
    仅返回压缩提示词模板供宿主 AGENT 使用，并对压缩后的结果进行字数范围校验。

    当 info 字数 > target_max 时，返回压缩提示词模板。宿主 AGENT 调用 LLM
    压缩后，应使用 validate_compressed_info 校验，或直接使用
    compress_info_with_retry 编排完整流程（含重试与截断兜底）。

    Args:
        info: 原始 info 文本（> target_max 字）
        target_min: 目标最小字数，默认 1200
        target_max: 目标最大字数，默认 1500

    Returns:
        压缩提示词模板字符串（供宿主 AGENT 调用 LLM 使用）

    Raises:
        ValueError: info 字数 ≤ target_max 时不触发压缩
    """
    length = len(info)
    if length <= target_max:
        raise ValueError(
            f"info 字数 {length} ≤ {target_max}，无需压缩"
        )

    logger.info(
        "触发 info 压缩",
        info_length=length,
        target_min=target_min,
        target_max=target_max,
    )
    return get_compress_prompt(info, target_min, target_max)


def compress_info_with_retry(
    info: str,
    compress_fn: Callable[[str], str],
    target_min: int = DEFAULT_TARGET_MIN,
    target_max: int = DEFAULT_TARGET_MAX,
    max_retries: int = MAX_RETRIES,
) -> str:
    """编排完整压缩流程（宿主 AGENT 传入 LLM 调用回调）。

    流程:
        1. 触发: info 字数 > target_max → 获取压缩提示词
        2. 调用 compress_fn(prompt) 得到压缩结果
        3. 校验: validate_compressed_info
        4. 字数 < target_min → 抛出 InfoTooShortError
        5. 字数 > target_max → get_retry_prompt → 重试 (最多 max_retries 次)
        6. 重试 max_retries 次仍 > target_max → truncate_info 截断兜底

    本函数不调用 LLM，LLM 调用通过 compress_fn 回调注入，由宿主 AGENT 提供。

    Args:
        info: 原始 info 文本
        compress_fn: LLM 压缩回调，接收提示词返回压缩结果
        target_min: 目标最小字数
        target_max: 目标最大字数
        max_retries: 最大重试次数，默认 2

    Returns:
        压缩后的 info 文本，字数 ∈ [target_min, target_max]
        （或截断兜底后字数 == target_max）

    Raises:
        ValueError: info 字数 ≤ target_max（无需压缩）
        InfoTooShortError: 压缩后字数 < target_min（压缩过度）
    """
    length = len(info)
    if length <= target_max:
        raise ValueError(
            f"info 字数 {length} ≤ {target_max}，无需压缩"
        )

    logger.info(
        "启动 info 压缩流程",
        info_length=length,
        target_min=target_min,
        target_max=target_max,
        max_retries=max_retries,
    )

    # 首次压缩
    prompt = get_compress_prompt(info, target_min, target_max)
    compressed = compress_fn(prompt)

    ok, action = validate_compressed_info(compressed, target_min, target_max)
    if ok:
        logger.info("info 压缩成功", compressed_length=len(compressed), retries=0)
        return compressed

    # 过短: 压缩过度，不可恢复，直接抛异常
    if action == "too_short":
        raise InfoTooShortError(
            f"info 压缩后字数 {len(compressed)} < {target_min}，压缩过度"
        )

    # 过长: 重试
    for attempt in range(1, max_retries + 1):
        logger.warning(
            "info 压缩结果过长，重试",
            compressed_length=len(compressed),
            attempt=attempt,
            max_retries=max_retries,
        )
        retry_prompt = get_retry_prompt(info, compressed, target_min, target_max)
        compressed = compress_fn(retry_prompt)

        ok, action = validate_compressed_info(compressed, target_min, target_max)
        if ok:
            logger.info(
                "info 压缩成功",
                compressed_length=len(compressed),
                retries=attempt,
            )
            return compressed

        if action == "too_short":
            raise InfoTooShortError(
                f"info 压缩后字数 {len(compressed)} < {target_min}，压缩过度"
            )

    # 重试 max_retries 次仍过长: 截断兜底
    logger.warning(
        "info 压缩重试耗尽，截断兜底",
        compressed_length=len(compressed),
        max_retries=max_retries,
    )
    return truncate_info(compressed, target_max)
