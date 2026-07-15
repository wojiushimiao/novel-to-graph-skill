"""novel-to-graph-skill · 工具函数包

双轨架构：tools/ 仅含纯 Python 工具函数，不调用 LLM、不进行智能体编排、不提供 CLI/HTTP API。
智能体读取 prompts/ 中的执行说明后，按需调用本包中的工具函数。

工具组：
- 组1 文本处理: text_chunker, rule_locator
- 组2 清洗校验: json_cleaner, schema_validator, low_value_filter
- 组3 归一化写入: quantifier, id_router, entity_merger, db_writer
- 组4 图分析报表: graph_builder, centrality_analyzer, community_detector,
                  bridges_finder, orphans_finder, stats_generator, html_renderer, exporter
"""

from .models import (
    # 数据模型
    Chunk,
    Entity,
    Relation,
    AnalysisResult,
    # 异常
    NovelAnalysisError,
    TextTooLargeError,
    EncodingError,
    EmptyFileError,
    SchemaValidationError,
    DatabaseWriteError,
    InfoCompressionError,
    # 配置常量
    MAX_TEXT_LENGTH,
    DEFAULT_CHUNK_SIZE,
    CHUNK_SIZE_TIERS,
    OVERLAP_SIZE,
    MAX_ENTITY_NAME_LENGTH,
    MIN_ENTITY_NAME_LENGTH,
    CONTEXT_WINDOW_SIZE,
    DB_WAL_MODE,
    TOP_N_CENTRALITY,
    TOP_N_COMMUNITIES,
    HTML_MAX_SIZE_MB,
    DB_MAX_SIZE_MB,
    BETWEENNESS_SAMPLE_THRESHOLD,
    BETWEENNESS_SAMPLE_K,
    # v0.5.0 A2: 差异化 Info Schema
    INFO_SCHEMA,
    INFO_TOTAL_MIN,
    INFO_TOTAL_MAX,
    get_info_schema,
    # v0.5.0 A3: 多档案并行
    MULTI_PROFILE_TYPES,
    # 合法值
    ENTITY_TYPES,
    COORD_DIMENSIONS,
    RELATION_TYPES,
    R_SUBTYPES,
    IMPORTANCE_LEVELS,
    IMPORTANCE_SCORE_MAP,
    STRENGTH_WEIGHT_MAP,
)

__all__ = [
    # 数据模型
    "Chunk", "Entity", "Relation", "AnalysisResult",
    # 异常
    "NovelAnalysisError", "TextTooLargeError", "EncodingError",
    "EmptyFileError", "SchemaValidationError", "DatabaseWriteError",
    "InfoCompressionError",
    # 配置常量
    "MAX_TEXT_LENGTH", "DEFAULT_CHUNK_SIZE", "CHUNK_SIZE_TIERS", "OVERLAP_SIZE",
    "MAX_ENTITY_NAME_LENGTH", "MIN_ENTITY_NAME_LENGTH", "CONTEXT_WINDOW_SIZE",
    "DB_WAL_MODE", "TOP_N_CENTRALITY", "TOP_N_COMMUNITIES",
    "HTML_MAX_SIZE_MB", "DB_MAX_SIZE_MB",
    "BETWEENNESS_SAMPLE_THRESHOLD", "BETWEENNESS_SAMPLE_K",
    # v0.5.0 A2: 差异化 Info Schema
    "INFO_SCHEMA", "INFO_TOTAL_MIN", "INFO_TOTAL_MAX", "get_info_schema",
    # v0.5.0 A3: 多档案并行
    "MULTI_PROFILE_TYPES",
    # 合法值
    "ENTITY_TYPES", "COORD_DIMENSIONS", "RELATION_TYPES", "R_SUBTYPES",
    "IMPORTANCE_LEVELS", "IMPORTANCE_SCORE_MAP", "STRENGTH_WEIGHT_MAP",
]

__version__ = "0.5.1"
