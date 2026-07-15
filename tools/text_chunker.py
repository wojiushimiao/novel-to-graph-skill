#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 文本分块工具

锚定: L2_数据模型与核心算法.md §2.1
      L3_接口契约与约束.md §1.1
      复用: novel-to-graph-db/scripts/chunker.py

提供按章节边界智能分块、滑动窗口重叠的能力。
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from .models import (
    Chunk,
    CHUNK_SIZE_TIERS,
    DEFAULT_CHUNK_SIZE,
    OVERLAP_SIZE,
    MAX_TEXT_LENGTH,
    EmptyFileError,
    EncodingError,
    TextTooLargeError,
)

logger = logging.getLogger(__name__)

# 章节边界检测模式（按优先级）
_CHAPTER_PATTERNS = [
    re.compile(r"(?:第[零一二三四五六七八九十百千\d]+章)", re.UNICODE),
    re.compile(r"(?:Chapter\s+\d+)", re.IGNORECASE),
    re.compile(r"(?:第[零一二三四五六七八九十百千\d]+回)", re.UNICODE),
    re.compile(r"(?:第[零一二三四五六七八九十百千\d]+卷)", re.UNICODE),
    re.compile(r"(?:第[零一二三四五六七八九十百千\d]+节)", re.UNICODE),
    re.compile(r"^\d+[\.\s、]\s*\S", re.MULTILINE),
]

# 候选编码（按优先级）
_DEFAULT_ENCODINGS = ["utf-8", "gbk", "gb2312", "utf-16"]


def read_file(
    file_path: str | Path,
    encodings: list[str] | None = None,
) -> str:
    """读取文本文件，自动检测编码。

    Args:
        file_path: 文件路径
        encodings: 尝试的编码列表（按优先级），None时用默认

    Returns:
        文本内容字符串

    Raises:
        FileNotFoundError: 文件不存在
        EmptyFileError: 文件为空
        TextTooLargeError: 文本超过最大长度限制
        EncodingError: 所有候选编码均失败
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    if path.stat().st_size == 0:
        raise EmptyFileError(f"文件为空: {path}")

    encs = encodings or _DEFAULT_ENCODINGS
    text: str | None = None
    last_err: Exception | None = None

    for enc in encs:
        try:
            text = path.read_text(encoding=enc)
            logger.info(f"读取文件成功: {path} (encoding={enc}, {len(text)} chars)")
            break
        except UnicodeDecodeError as exc:
            last_err = exc
            logger.debug(f"编码 {enc} 解码失败: {exc}")
            continue

    if text is None:
        raise EncodingError(
            f"所有候选编码均失败: {encs}; 最后错误: {last_err}"
        )

    if len(text) > MAX_TEXT_LENGTH:
        raise TextTooLargeError(
            f"文本长度 {len(text)} 超过最大限制 {MAX_TEXT_LENGTH}"
        )

    return text


def validate_text_length(text: str) -> None:
    """验证文本长度是否在限制内。

    Args:
        text: 原始文本

    Raises:
        TextTooLargeError: 超长
    """
    if len(text) > MAX_TEXT_LENGTH:
        raise TextTooLargeError(
            f"文本长度 {len(text)} 超过最大限制 {MAX_TEXT_LENGTH}"
        )


def detect_chapter_boundaries(text: str) -> list[tuple[int, str | None]]:
    """检测章节边界。

    扫描文本，识别章节标题行（支持6种正则模式）。

    Args:
        text: 原始文本

    Returns:
        边界列表 [(字符偏移, 章节标题|None), ...]
        第一个元素为 (0, None)，最后一个为 (len(text), None)
    """
    boundaries: list[tuple[int, str | None]] = [(0, None)]
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            for pattern in _CHAPTER_PATTERNS:
                if pattern.match(stripped):
                    boundaries.append((offset, stripped[:80]))
                    break
        offset += len(line) + 1  # +1 for \n
    boundaries.append((len(text), None))
    return boundaries


def detect_chunk_size(model_ctx_tokens: int | None = None) -> int:
    """根据模型上下文窗口大小返回合适的 chunk 大小。

    检测优先级:
    1. 显式传入 model_ctx_tokens
    2. 环境变量 NOVEL_ANALYSIS_MODEL_CTX
    3. 默认 DEFAULT_CHUNK_SIZE

    Args:
        model_ctx_tokens: 模型上下文窗口大小（token 数），可选

    Returns:
        chunk 大小（chars），按 CHUNK_SIZE_TIERS 阈值映射

    Raises:
        ValueError: model_ctx_tokens < 0
    """
    import os

    if model_ctx_tokens is None:
        env_val = os.environ.get("NOVEL_ANALYSIS_MODEL_CTX")
        if env_val:
            try:
                model_ctx_tokens = int(env_val)
            except ValueError:
                pass

    if model_ctx_tokens is None:
        return DEFAULT_CHUNK_SIZE

    if model_ctx_tokens < 0:
        raise ValueError(f"model_ctx_tokens 不能为负值: {model_ctx_tokens}")

    # 按阈值降序遍历 CHUNK_SIZE_TIERS
    for threshold in sorted(CHUNK_SIZE_TIERS.keys(), reverse=True):
        if model_ctx_tokens >= threshold:
            return CHUNK_SIZE_TIERS[threshold]

    # 兜底（理论上不可达，CHUNK_SIZE_TIERS[0] 覆盖所有非负值）
    return 4_000  # pragma: no cover


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = OVERLAP_SIZE,
    source: str = "novel",
    model_ctx_tokens: int | None = None,  # v0.5.0 A1: 自适应 chunk 大小
    pack_chapters: bool = True,           # v0.5.1: 短章打包（20K 甜点）
) -> list[Chunk]:
    """按章节边界分块。

    优先按章节边界分块；超长章节按段落边界二次分块；
    块间保留 overlap 字符的上下文重叠。

    v0.5.1 短章打包 (pack_chapters=True, 默认):
        对均匀短章节源（如网文，每章 ~2K 字），若逐章成块会产出大量
        远小于 chunk_size 的碎块（实测每章一块 → 3000+ 碎块），使
        自适应 chunk 大小完全失效。开启打包后，连续短章会被贪心合并
        至接近 chunk_size（默认 20K），命中"20K 甜点"——抽取密度与
        信息深度最优、长上下文注意力衰减最小。超长单章（> chunk_size）
        仍按段落二次分块。pack_chapters=False 时退回逐章成块（旧行为）。

    Args:
        text: 原始文本
        chunk_size: 目标块大小（字符），默认 20000 (DEFAULT_CHUNK_SIZE)
        overlap: 块间重叠大小（字符），默认 1000
        source: 源标识（用于生成 chunk_id）
        model_ctx_tokens: 模型上下文（token），非空时自适应覆盖 chunk_size
        pack_chapters: 是否打包连续短章至 chunk_size（默认 True）

    Returns:
        Chunk 列表（非空，index 从 0 递增连续无跳跃）
    """
    # v0.5.0 A1: 自适应 chunk 大小
    if model_ctx_tokens is not None and chunk_size == DEFAULT_CHUNK_SIZE:
        chunk_size = detect_chunk_size(model_ctx_tokens)

    validate_text_length(text)

    boundaries = detect_chapter_boundaries(text)
    chunks: list[Chunk] = []
    chunk_idx = 0

    # v0.5.1 短章打包缓冲区
    pack_buf = ""                       # 累积内容
    pack_start: int | None = None       # 缓冲区起始字符偏移
    pack_first_title: str | None = None  # 打包内首章标题
    pack_count = 0                      # 打包内章节数

    def _flush_pack() -> None:
        nonlocal pack_buf, pack_start, pack_first_title, pack_count, chunk_idx
        if pack_buf.strip():
            name = pack_first_title or f"片段{chunk_idx}"
            if pack_count > 1:
                name = f"{name} …(+{pack_count - 1}章)"
            chunks.append(Chunk(
                index=chunk_idx,
                content=pack_buf,
                chapter=name,
                char_offset=pack_start if pack_start is not None else 0,
                char_count=len(pack_buf),
                chunk_id=generate_chunk_id(source, chunk_idx),
            ))
            chunk_idx += 1
        pack_buf = ""
        pack_start = None
        pack_first_title = None
        pack_count = 0

    for i in range(len(boundaries) - 1):
        start, chapter_title = boundaries[i]
        end = boundaries[i + 1][0]
        segment = text[start:end]

        if not segment.strip():
            continue

        chapter_name = chapter_title or f"片段{chunk_idx}"

        if len(segment) <= chunk_size:
            if not pack_chapters:
                # 旧行为：整章节为一个块
                chunks.append(Chunk(
                    index=chunk_idx,
                    content=segment,
                    chapter=chapter_name,
                    char_offset=start,
                    char_count=len(segment),
                    chunk_id=generate_chunk_id(source, chunk_idx),
                ))
                chunk_idx += 1
                continue
            # v0.5.1 打包：连续短章贪心合并至 chunk_size
            if pack_buf and len(pack_buf) + len(segment) > chunk_size:
                _flush_pack()
            if pack_start is None:
                pack_start = start
                pack_first_title = chapter_name
            pack_buf += segment
            pack_count += 1
        else:
            # 超长单章：先冲刷待打包缓冲，再按段落二次分块 + 滑动窗口重叠
            if pack_chapters:
                _flush_pack()
            paragraphs = segment.split("\n")
            current = ""
            current_offset = start
            for para in paragraphs:
                if len(current) + len(para) + 1 > chunk_size and current:
                    # 切分当前块
                    overlap_text = current[-overlap:] if len(current) > overlap else current
                    chunks.append(Chunk(
                        index=chunk_idx,
                        content=current,
                        chapter=chapter_name,
                        char_offset=current_offset,
                        char_count=len(current),
                        chunk_id=generate_chunk_id(source, chunk_idx),
                    ))
                    chunk_idx += 1
                    current_offset = current_offset + len(current) - len(overlap_text)
                    current = overlap_text + para + "\n"
                else:
                    current += para + "\n"
            if current.strip():
                chunks.append(Chunk(
                    index=chunk_idx,
                    content=current,
                    chapter=chapter_name,
                    char_offset=current_offset,
                    char_count=len(current),
                    chunk_id=generate_chunk_id(source, chunk_idx),
                ))
                chunk_idx += 1

    # 冲刷末尾待打包缓冲
    if pack_chapters:
        _flush_pack()

    logger.info(f"分块完成: {len(chunks)} 个块 (源={source}, 打包={pack_chapters}, 目标={chunk_size})")
    return chunks


def chunk_file(
    file_path: str | Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = OVERLAP_SIZE,
    encodings: list[str] | None = None,
) -> list[Chunk]:
    """从文件读取并分块。

    Args:
        file_path: 文本文件路径
        chunk_size: 目标块大小
        overlap: 块间重叠大小
        encodings: 候选编码列表

    Returns:
        Chunk 列表
    """
    path = Path(file_path)
    text = read_file(path, encodings=encodings)
    source = path.stem
    return chunk_text(text, chunk_size=chunk_size, overlap=overlap, source=source)


def generate_chunk_id(source: str, chunk_idx: int) -> str:
    """生成块唯一 ID。

    Args:
        source: 源标识（如文件名）
        chunk_idx: 块序号

    Returns:
        12 位 hex 字符串（MD5(source+index) 前12位）
    """
    raw = f"{source}_{chunk_idx}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def estimate_total_chunks(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    pack_chapters: bool = True,
) -> int:
    """估算总块数（不实际分块）。

    Args:
        text: 原始文本
        chunk_size: 目标块大小
        pack_chapters: 是否打包连续短章（默认 True，与 chunk_text 一致）

    Returns:
        估算的块数
    """
    boundaries = detect_chapter_boundaries(text)
    total = 0
    pack_len = 0  # v0.5.1 打包缓冲累计长度
    for i in range(len(boundaries) - 1):
        seg_len = boundaries[i + 1][0] - boundaries[i][0]
        if seg_len <= 0:
            continue
        if seg_len <= chunk_size:
            if not pack_chapters:
                total += 1
                continue
            # 打包：累计短章，超出目标则冲刷计数
            if pack_len and pack_len + seg_len > chunk_size:
                total += 1
                pack_len = 0
            pack_len += seg_len
        else:
            if pack_chapters and pack_len:
                total += 1
                pack_len = 0
            total += max(1, seg_len // (chunk_size - OVERLAP_SIZE) + 1)
    if pack_chapters and pack_len:
        total += 1
    return total
