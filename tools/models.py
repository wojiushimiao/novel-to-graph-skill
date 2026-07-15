#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 数据模型与异常定义

锚定: L2_数据模型与核心算法.md §一·数据模型
      L3_接口契约与约束.md §五·错误类型定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─── 异常层级 ──────────────────────────────────────────────

class NovelAnalysisError(Exception):
    """novel-analysis-skill 基础异常。"""


class TextTooLargeError(NovelAnalysisError):
    """文本超过最大长度限制 (MAX_TEXT_LENGTH=50_000_000)。"""


class EncodingError(NovelAnalysisError):
    """所有候选编码均无法解析文件。"""


class EmptyFileError(NovelAnalysisError):
    """文件为空（0字节或仅空白）。"""


class SchemaValidationError(NovelAnalysisError):
    """LLM 输出 JSON Schema 校验失败。"""


class DatabaseWriteError(NovelAnalysisError):
    """SQLite 写入失败（事务回滚后抛出）。"""


class InfoCompressionError(NovelAnalysisError):
    """info 字段压缩相关异常基类。

    锚定: L3_接口契约与约束.md §1.1.4 (info_compressor)
    """


# ─── 核心数据模型 ──────────────────────────────────────────

@dataclass
class Chunk:
    """文本块。

    由 text_chunker.chunk_text 输出，作为后续工具函数的输入单位。
    """
    index: int                 # 块序号（0-based 递增）
    content: str               # 文本内容
    chapter: str               # 所属章节标题（无章节时为"片段N"）
    char_offset: int           # 在原文中的字符偏移
    char_count: int            # 字符数 = len(content)
    chunk_id: str              # 唯一ID（MD5(source+index)前12位）


@dataclass
class Entity:
    """实体档案。

    由智能体基于 LLM 输出 + id_router 处理后构造。
    """
    id: str                    # "{type[0].upper()}_{name}"，如 "C_莫凡"
    name: str                  # 实体显示名称
    type: str                  # character|location|event|item|rule|system
    base_info: dict = field(default_factory=dict)      # {name, aliases, first_appearance, entity_description}
    detail_info: dict = field(default_factory=dict)   # {attributes, relationships_summary, character_arc}
    stitch_tags: dict = field(default_factory=dict)   # {sigma, epsilon, kappa}
    coords: dict = field(default_factory=dict)        # {T: str, L: str, C: str, E: str, R: str} 五维唯一值
    info: str = ""              # 实体详情（500-1500字 LLM 语义提炼，v0.4.0 新增）
    source_chapter: str = ""   # 首次出现的章节
    char_offset: int = 0       # 首次出现的字符偏移


@dataclass
class Relation:
    """实体间关系。"""
    source_id: str             # 源实体 ID
    target_id: str             # 目标实体 ID
    relation_type: str         # located_in|participates_in|relates_to|evolves_to|causes|belongs_to|references
    strength: str = "weak"     # strong|weak
    description: str = ""      # 关系描述
    source_chapter: str = ""   # 关系出现的章节


@dataclass
class AnalysisResult:
    """图分析结果。

    由图分析工具组共同填充。
    """
    degree_centrality: dict[str, float] = field(default_factory=dict)
    betweenness_centrality: dict[str, float] = field(default_factory=dict)
    eigenvector_centrality: dict[str, float] = field(default_factory=dict)
    communities: dict[int, list[str]] = field(default_factory=dict)
    bridges: list[dict] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


# ─── 配置常量 ──────────────────────────────────────────────

MAX_TEXT_LENGTH = 50_000_000        # 5000万字
DEFAULT_CHUNK_SIZE = 20000          # 默认块大小(字符) — v0.5.0 从 8000 升至 20000
OVERLAP_SIZE = 1000                 # 块间重叠(字符)
# v0.5.0 A1: 自适应 chunk 大小三档映射 — 阈值(token) → chunk大小(chars)
CHUNK_SIZE_TIERS = {
    128_000: 20_000,                # ≥128K 上下文 → 20K chars
    32_000: 8_000,                  # 32K-128K 上下文 → 8K chars
    0: 4_000,                       # <32K 上下文 → 4K chars（降级）
}
MAX_ENTITY_NAME_LENGTH = 20         # 实体名最大长度
MIN_ENTITY_NAME_LENGTH = 2          # 实体名最小长度
CONTEXT_WINDOW_SIZE = 200           # 坐标提取上下文窗口(字符)
DB_WAL_MODE = True                  # SQLite WAL模式
TOP_N_CENTRALITY = 100              # 中心性Top-N截断
TOP_N_COMMUNITIES = 20              # 社群Top-N截断
HTML_MAX_SIZE_MB = 50               # HTML报表最大体积(MB)
DB_MAX_SIZE_MB = 500                # SQLite数据库最大体积(MB)
BETWEENNESS_SAMPLE_THRESHOLD = 1000  # 介数中心性抽样阈值
BETWEENNESS_SAMPLE_K = 1000         # 介数中心性抽样数

# 合法实体类型
ENTITY_TYPES = ("character", "location", "event", "item", "rule", "system", "monster", "knowledge", "E_module")

# v0.5.0 A2: 差异化 Info Schema — 按实体类型定义 Info 段结构
# 格式: {entity_type: ((段名, 最低字数), ...)}
INFO_SCHEMA: dict[str, tuple[tuple[str, int], ...]] = {
    "event": (("起因", 100), ("经过", 200), ("结果", 100), ("模块定位", 100)),
    "character": (("身份背景", 100), ("性格特征", 100), ("能力体系", 100), ("人际关系", 100), ("人物弧光", 100)),
    "location": (("地理描述", 100), ("政治经济", 100), ("关联角色", 100), ("剧情作用", 100)),
    "item": (("来源", 100), ("功能", 100), ("持有者变更", 100), ("剧情作用", 100)),
    "rule": (("定义", 100), ("约束条件", 100), ("例外情况", 100), ("剧情影响", 100)),
    "system": (("体系概述", 100), ("层级结构", 100), ("核心规则", 100), ("剧情作用", 100)),
}

# v0.5.1 B2: 人物小传 Schema — 统合性人物简介
# 锚定: v0.5.1_升级/00_技术锚定/L2_数据模型与核心算法.md §1.2
CHARACTER_SYNTHESIS_SCHEMA: list[tuple[str, int]] = [
    ("身份概述", 150),   # ≥150 字
    ("性格演变", 150),   # ≥150 字
    ("能力成长", 150),   # ≥150 字
    ("关系网络", 150),   # ≥150 字
    ("人物弧光", 200),   # ≥200 字
]
# 总字数范围: 800-2000
CHARACTER_SYNTHESIS_TOTAL_MIN = 800
CHARACTER_SYNTHESIS_TOTAL_MAX = 2000

INFO_TOTAL_MIN: dict[str, int] = {
    "event": 500, "character": 500,
    "location": 400, "item": 400, "rule": 400, "system": 400,
}
INFO_TOTAL_MAX: dict[str, int] = {
    "event": 1500, "character": 1500,
    "location": 1200, "item": 1200, "rule": 1200, "system": 1200,
}


def get_info_schema(entity_type: str) -> tuple[tuple[str, int], ...]:
    """返回指定实体类型的 Info Schema 段定义。

    Args:
        entity_type: 实体类型（event/character/location/item/rule/system）

    Returns:
        ((段名, 最低字数), ...) 元组。若类型不在 INFO_SCHEMA 中，返回空元组。
    """
    return INFO_SCHEMA.get(entity_type, ())

# 合法坐标维度（v0.4.0 五维，移除 K 由 E_module 剧情模块替代）
COORD_DIMENSIONS = ("T", "L", "C", "E", "R")

# 合法关系类型 (轴关系模型 v0.4.0)
# 轴关系：结构性索引，服务于扇入
# 直接关系：仅限强关联实体的扇出
RELATION_TYPES = (
    "T_main",      # 时序主轴：核心主线事件按时序串联（特殊扇出）
    "T_branch",    # 时序分支轴：鱼骨图分解主轴事件
    "S_topo",      # 空间拓扑辅轴：地理状态拓扑归属
    "A_causal",    # 因果辅轴：事件间因果关系
    "A_arc",       # 角色弧光辅轴：角色发展里程碑
    "R_strong",    # 强关联：直接关系（个人支线/专属武器功法/师徒父子等）
    "evolves_to",  # v0.5.0 A3: 角色演化（同角色跨卷档案串联，形成人物弧光链）
)

# v0.5.0 A3: 多档案并行 — 哪些实体类型需要按 (name, type, t_main_volume) 合并
MULTI_PROFILE_TYPES = ("character",)

# 实体出边（扇出）上限 — 防止上下文过载
# 扇入不受限制（无上下文负担）
# v0.4.0 微调: location 允许 S_topo 出边（L→E_module/E_event），从辅轴提升为平行主轴
ENTITY_OUT_EDGE_LIMITS = {
    "character": 5,    # 角色仅限强关联扇出
    "location": 20,    # 地点 S_topo 出边（L→E_module/E_event 空间索引，微调新增）
    "event": 3,        # 事件仅T_main/A_causal扇出
    "item": 0,         # 物品不扇出，仅被扇入
    "rule": 0,         # 规则不扇出，仅被扇入
    "system": 0,       # 系统不扇出，仅被扇入
    "monster": 0,      # 魔物不扇出，仅被扇入
    "knowledge": 0,    # 知识不扇出，仅被扇入
    "E_module": 0,     # 剧情模块不扇出（T_main 由 timeline_skeleton_builder 集中构建）
}

# 轴关系映射：旧关系类型 → 新轴关系类型
LEGACY_TO_AXIS_MAP = {
    "located_in": "S_topo",
    "belongs_to": "S_topo",
    "participates_in": "T_branch",
    "causes": "A_causal",
    "evolves_to": "A_arc",
    "relates_to": "R_strong",
    "references": "R_strong",
}

# 合法 R 维度子类
R_SUBTYPES = (
    "R_power", "R_philosophy", "R_cultivation",
    "R_energy_tech", "R_law", "R_system",
)

# 重要度合法值
IMPORTANCE_LEVELS = ("high", "medium", "low")

# 重要度→数值映射
IMPORTANCE_SCORE_MAP = {
    "high": 0.85,
    "medium": 0.50,
    "low": 0.15,
}

# 关系强度→权重映射
STRENGTH_WEIGHT_MAP = {
    "strong": 1.0,
    "weak": 0.5,
}
