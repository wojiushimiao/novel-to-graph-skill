#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · 摘要语义聚类器（SemanticClusterer）

锚定: v0.4.1_plan_final.md §T-C2
功能: 对 SummaryBuffer flush 输出的短期摘要运行 3 类聚类，识别剧情结构边界。

聚类类型（S2.5 阶段，仅识别剧情结构边界）:
1. 时序聚类：按顺序识别连续阶段边界（T_main 卷候选）
2. 场景聚类：按 L 坐标识别地点转移链（E_module 边界辅助）
3. 实体聚类：按 C 坐标识别角色活跃期（E_module 边界辅助）

注: 事件聚类和规则聚类属于 S3 阶段（实体提取），不在此处执行。

算法规格:
- embedding 模型: BAAI/bge-small-zh-v1.5（本地推理，无 LLM 调用）
- 相似度度量: cosine similarity
- T_main 卷边界: cosine < 0.55 视为主题切换
- E_module 边界: cosine < 0.70 视为子主题切换
- 连续 ≥5 chunk 相似度 > 0.75 → 同一 E_module 候选
- 降级方案: embedding 不可用时降级为关键词重合度（Jaccard ≥0.3）
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    from .timeline_skeleton_builder import _infer_stage
except ImportError:
    from timeline_skeleton_builder import _infer_stage

# 聚类阈值
T_MAIN_BOUNDARY_THRESHOLD = 0.55      # T_main 卷边界
E_MODULE_BOUNDARY_THRESHOLD = 0.70    # E_module 边界
E_MODULE_COHESION_THRESHOLD = 0.75    # E_module 内聚阈值
MIN_E_MODULE_CHUNKS = 5               # E_module 最小 chunk 数
KEYWORD_FALLBACK_THRESHOLD = 0.30     # 降级关键词重合度阈值
SCENE_CLUSTER_THRESHOLD = 0.70        # 场景聚类（地点转移）边界阈值
ENTITY_CLUSTER_THRESHOLD = 0.65       # 实体聚类（角色活跃期）边界阈值

# 模块级模型缓存（避免重复加载 SentenceTransformer）
_EMBEDDING_MODEL_CACHE: dict[str, Any] = {}

# 中文停用词（简化版）
_STOP_WORDS = frozenset({
    "的", "了", "在", "是", "和", "与", "或", "也", "都", "但", "而", "则",
    "这", "那", "他", "她", "它", "们", "我", "你", "上", "下", "中",
    "进行", "开始", "结束", "到", "去", "来", "被", "把", "让", "使",
    "一个", "一种", "一些", "可以", "能够", "需要", "应该",
})

# 场景聚类：地点关键词集
_LOCATION_KEYWORDS: frozenset[str] = frozenset({
    "城市", "学院", "广场", "山脉", "森林", "宫殿", "房间", "大厅",
    "街道", "城堡", "村庄", "酒馆", "寺庙", "洞穴", "沙漠", "海洋",
    "天空", "地下", "山谷", "河流", "湖泊", "草原", "荒原", "沼泽",
    "战场", "塔楼", "城墙", "大门", "走廊", "密室", "地下室", "阁楼",
    "码头", "港口", "市场", "商铺", "客栈", "府邸", "宅院", "花园",
    "帝都", "魔都", "小镇", "山村", "岛", "峰", "崖", "谷", "渊",
    "学校", "教室", "训练场", "竞技场", "图书馆", "实验室", "食堂",
    "宿舍", "医院", "基地", "总部", "据点", "营地", "圣殿", "神殿",
})

# 实体聚类：常见中文姓氏前缀集
_COMMON_SURNAMES: frozenset[str] = frozenset({
    "莫", "张", "李", "王", "赵", "陈", "刘", "杨", "黄", "周",
    "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林",
    "郑", "谢", "罗", "梁", "宋", "唐", "韩", "曹", "许", "邓",
    "萧", "冯", "曾", "程", "蔡", "彭", "潘", "袁", "于", "董",
    "余", "苏", "叶", "吕", "魏", "蒋", "田", "杜", "丁", "沈",
    "姜", "范", "江", "傅", "钟", "卢", "汪", "戴", "崔", "任",
    "陆", "廖", "姚", "方", "金", "邱", "夏", "谭", "韦", "贾",
    "邹", "石", "熊", "孟", "秦", "阎", "薛", "侯", "雷", "白",
    "龙", "段", "郝", "孔", "邵", "史", "毛", "常", "万", "顾",
    "赖", "武", "康", "贺", "严", "尹", "钱", "施", "牛", "洪", "龚",
    "慕容", "欧阳", "上官", "司马", "诸葛", "令狐", "端木", "轩辕",
    "皇甫", "尉迟", "东方", "独孤", "南宫", "夏侯", "公孙", "长孙",
})


def cluster_summaries(
    summaries: list[dict],
    use_embedding: bool = True,
    embedding_model: str = "BAAI/bge-small-zh-v1.5",
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """对摘要列表运行 3 类聚类。

    Args:
        summaries: SummaryBuffer.flush() 输出的摘要列表，每个含 chunk_index/summary/timestamp
        use_embedding: 是否使用 embedding 模型；False 强制使用关键词降级模式
        embedding_model: embedding 模型名（默认 BAAI/bge-small-zh-v1.5）
        thresholds: 自定义聚类阈值（v0.5.1 B1）；None 时使用模块常量。
            支持的键:
            - "temporal": 覆盖 T_MAIN_BOUNDARY_THRESHOLD (默认 0.55)
            - "scene":   覆盖 SCENE_CLUSTER_THRESHOLD (默认 0.70)
            - "entity":  覆盖 ENTITY_CLUSTER_THRESHOLD (默认 0.65)

    Returns:
        {
            "t_main_candidates": [{id, name, range, theme, stage}],
            "module_candidates": [{id, name, range, theme, stage}],
            "clusters": [{type, entities, start_chunk, end_chunk}],
        }
    """
    if not summaries:
        return {
            "t_main_candidates": [],
            "module_candidates": [],
            "clusters": [],
        }

    # Resolve thresholds (v0.5.1 B1: 支持自定义阈值)
    temporal_thresh = thresholds.get("temporal", T_MAIN_BOUNDARY_THRESHOLD) if thresholds else T_MAIN_BOUNDARY_THRESHOLD
    scene_thresh = thresholds.get("scene", SCENE_CLUSTER_THRESHOLD) if thresholds else SCENE_CLUSTER_THRESHOLD
    entity_thresh = thresholds.get("entity", ENTITY_CLUSTER_THRESHOLD) if thresholds else ENTITY_CLUSTER_THRESHOLD

    # 按 chunk_index 排序
    sorted_summaries = sorted(summaries, key=lambda s: s["chunk_index"])
    texts = [s["summary"] for s in sorted_summaries]
    indices = [s["chunk_index"] for s in sorted_summaries]

    # 计算相似度矩阵
    if use_embedding:
        try:
            sim_matrix = _compute_embedding_similarity(texts, embedding_model)
        except Exception as exc:
            logger.warning(f"embedding 模型不可用，降级为关键词模式: {exc}")
            sim_matrix = _compute_keyword_similarity(texts)
    else:
        sim_matrix = _compute_keyword_similarity(texts)

    # 时序聚类 → T_main 卷候选
    t_main_candidates = _temporal_cluster(sorted_summaries, sim_matrix, temporal_thresh)

    # 场景聚类 → E_module 候选（地点转移）
    module_candidates = _scene_cluster(sorted_summaries, sim_matrix, scene_thresh)

    # 实体聚类 → E_module 候选补充（角色活跃期）
    entity_modules = _entity_cluster(sorted_summaries, sim_matrix, entity_thresh)
    module_candidates.extend(entity_modules)

    # 去重（合并重叠的 E_module 候选）
    module_candidates = _deduplicate_modules(module_candidates)

    # 后处理：使用实际总卷数更新 T_main 候选的 stage
    total_volumes = len(t_main_candidates)
    for i, candidate in enumerate(t_main_candidates):
        candidate["stage"] = _infer_stage(i, total_volumes)

    return {
        "t_main_candidates": t_main_candidates,
        "module_candidates": module_candidates,
        "clusters": _build_clusters_info(t_main_candidates, module_candidates),
    }


# ─── 内部：相似度计算 ───────────────────────────────────

def _compute_embedding_similarity(texts: list[str], model_name: str) -> list[list[float]]:
    """使用 sentence-transformer 计算 embedding 余弦相似度矩阵。"""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise ImportError(f"sentence-transformer 或 numpy 不可用: {exc}")

    if model_name not in _EMBEDDING_MODEL_CACHE:
        logger.info(f"加载 embedding 模型: {model_name}")
        _EMBEDDING_MODEL_CACHE[model_name] = SentenceTransformer(model_name)

    model = _EMBEDDING_MODEL_CACHE[model_name]
    embeddings = model.encode(texts, convert_to_numpy=True)
    # 归一化后点积 = cosine 相似度
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normalized = embeddings / norms
    sim_matrix = (normalized @ normalized.T).tolist()
    return sim_matrix


def _compute_keyword_similarity(texts: list[str]) -> list[list[float]]:
    """使用关键词重合度（Jaccard）计算相似度矩阵（降级模式）。"""
    keyword_sets = [_extract_keywords(t) for t in texts]
    n = len(texts)
    sim_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim_matrix[i][i] = 1.0
        for j in range(i + 1, n):
            sim = _jaccard_similarity(keyword_sets[i], keyword_sets[j])
            sim_matrix[i][j] = sim
            sim_matrix[j][i] = sim
    return sim_matrix


def _extract_keywords(text: str) -> set[str]:
    """从文本提取关键词（简单分词，去除停用词）。"""
    if not text:
        return set()
    # 简单字符级 n-gram 分词（中文）
    # 提取 2-3 字的连续中文片段
    keywords: set[str] = set()
    cleaned = re.sub(r"[^\u4e00-\u9fa5]+", " ", text)
    tokens = cleaned.split()
    for token in tokens:
        if len(token) >= 2:
            # 2-3 字滑动窗口
            for size in (2, 3):
                for i in range(len(token) - size + 1):
                    word = token[i:i + size]
                    if word not in _STOP_WORDS:
                        keywords.add(word)
    return keywords


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """计算两个集合的 Jaccard 相似度。

    Args:
        set_a: 集合 A
        set_b: 集合 B

    Returns:
        Jaccard 相似度 ∈ [0, 1]，空集返回 0.0
    """
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


# ─── 内部：聚类算法 ─────────────────────────────────────

def _temporal_cluster(
    summaries: list[dict],
    sim_matrix: list[list[float]],
    threshold: float = T_MAIN_BOUNDARY_THRESHOLD,
) -> list[dict[str, Any]]:
    """时序聚类：按顺序识别阶段边界（T_main 卷候选）。

    边界判定：相邻 chunk 相似度 < threshold 视为卷边界。

    Args:
        summaries: 已按 chunk_index 排序的摘要列表
        sim_matrix: 相似度矩阵
        threshold: 卷边界阈值（默认 T_MAIN_BOUNDARY_THRESHOLD=0.55）
    """
    if not summaries:
        return []

    t_main_candidates: list[dict[str, Any]] = []
    current_start = 0

    for i in range(1, len(summaries)):
        sim = sim_matrix[i - 1][i]
        if sim < threshold:
            # 检测到边界，闭合当前卷
            t_main_candidates.append(_make_t_main_candidate(
                summaries, current_start, i - 1, len(t_main_candidates),
            ))
            current_start = i

    # 闭合最后一个卷
    t_main_candidates.append(_make_t_main_candidate(
        summaries, current_start, len(summaries) - 1, len(t_main_candidates),
    ))

    return t_main_candidates


def _scene_cluster(
    summaries: list[dict],
    sim_matrix: list[list[float]],
    threshold: float = SCENE_CLUSTER_THRESHOLD,
) -> list[dict[str, Any]]:
    """场景聚类：按地点转移识别 E_module 边界。

    使用地点关键词调整相似度矩阵，共享地点关键词的摘要对相似度乘以 1.2（上限 1.0）。

    Args:
        summaries: 已按 chunk_index 排序的摘要列表
        sim_matrix: 相似度矩阵
        threshold: 场景聚类边界阈值（默认 SCENE_CLUSTER_THRESHOLD=0.70）
    """
    adjusted = _adjust_sim_for_locations(sim_matrix, summaries)
    return _cohesion_cluster(summaries, adjusted, threshold)


def _entity_cluster(
    summaries: list[dict],
    sim_matrix: list[list[float]],
    threshold: float = ENTITY_CLUSTER_THRESHOLD,
) -> list[dict[str, Any]]:
    """实体聚类：按角色活跃期识别 E_module 边界。

    使用角色名关键词调整相似度矩阵，共享角色名的摘要对相似度乘以 1.2（上限 1.0）。

    Args:
        summaries: 已按 chunk_index 排序的摘要列表
        sim_matrix: 相似度矩阵
        threshold: 实体聚类边界阈值（默认 ENTITY_CLUSTER_THRESHOLD=0.65）
    """
    adjusted = _adjust_sim_for_characters(sim_matrix, summaries)
    return _cohesion_cluster(summaries, adjusted, threshold)


def _cohesion_cluster(
    summaries: list[dict],
    sim_matrix: list[list[float]],
    threshold: float,
) -> list[dict[str, Any]]:
    """内聚聚类：连续相似度 > threshold 的 chunk 归为同一 E_module 候选。"""
    if not summaries:
        return []

    candidates: list[dict[str, Any]] = []
    current_start = 0

    for i in range(1, len(summaries)):
        sim = sim_matrix[i - 1][i]
        if sim < threshold:
            # 边界：闭合当前候选（需满足最小 chunk 数）
            if i - current_start >= MIN_E_MODULE_CHUNKS:
                candidates.append(_make_module_candidate(
                    summaries, current_start, i - 1, len(candidates),
                ))
            current_start = i

    # 闭合最后一个候选
    if len(summaries) - current_start >= MIN_E_MODULE_CHUNKS:
        candidates.append(_make_module_candidate(
            summaries, current_start, len(summaries) - 1, len(candidates),
        ))

    # 若无候选（chunk 总数不足），返回单一候选
    if not candidates and summaries:
        candidates.append(_make_module_candidate(
            summaries, 0, len(summaries) - 1, 0,
        ))

    return candidates


# ─── 内部：相似度矩阵调整（关键词加权） ──────────────────

def _adjust_sim_for_locations(
    sim_matrix: list[list[float]],
    summaries: list[dict],
) -> list[list[float]]:
    """调整相似度矩阵：共享地点关键词的摘要对相似度乘以 1.2（上限 1.0）。

    对每对摘要，若它们共享至少一个地点关键词（_LOCATION_KEYWORDS），
    则将相似度提高 20%，上限 1.0。
    """
    n = len(summaries)
    adjusted = [row[:] for row in sim_matrix]
    for i in range(n):
        locs_i = _extract_location_keywords(summaries[i]["summary"])
        if not locs_i:
            continue
        for j in range(i + 1, n):
            locs_j = _extract_location_keywords(summaries[j]["summary"])
            if locs_i & locs_j:
                boost = min(adjusted[i][j] * 1.2, 1.0)
                adjusted[i][j] = boost
                adjusted[j][i] = boost
    return adjusted


def _adjust_sim_for_characters(
    sim_matrix: list[list[float]],
    summaries: list[dict],
) -> list[list[float]]:
    """调整相似度矩阵：共享角色名的摘要对相似度乘以 1.2（上限 1.0）。

    对每对摘要，若它们共享至少一个角色名（基于 _COMMON_SURNAMES 提取），
    则将相似度提高 20%，上限 1.0。
    """
    n = len(summaries)
    adjusted = [row[:] for row in sim_matrix]
    for i in range(n):
        chars_i = _extract_character_names(summaries[i]["summary"])
        if not chars_i:
            continue
        for j in range(i + 1, n):
            chars_j = _extract_character_names(summaries[j]["summary"])
            if chars_i & chars_j:
                boost = min(adjusted[i][j] * 1.2, 1.0)
                adjusted[i][j] = boost
                adjusted[j][i] = boost
    return adjusted


def _extract_location_keywords(text: str) -> set[str]:
    """从文本中提取地点关键词。

    Args:
        text: 摘要文本

    Returns:
        匹配到的地点关键词集合
    """
    if not text:
        return set()
    return {kw for kw in _LOCATION_KEYWORDS if kw in text}


def _extract_character_names(text: str) -> set[str]:
    """从文本中提取潜在角色名（2-3 字，以常见姓氏开头）。

    使用正则匹配：姓氏（_COMMON_SURNAMES） + 1-2 个中文字符。

    Args:
        text: 摘要文本

    Returns:
        匹配到的角色名集合
    """
    if not text:
        return set()
    # 构建姓氏正则：按长度降序排列避免短姓氏优先匹配长姓氏
    surnames_sorted = sorted(_COMMON_SURNAMES, key=len, reverse=True)
    pattern = re.compile(r"(" + "|".join(surnames_sorted) + r")[\u4e00-\u9fa5]{1,2}")
    return set(pattern.findall(text))


# ─── 内部：候选构造 ─────────────────────────────────────

def _make_t_main_candidate(
    summaries: list[dict],
    start_idx: int,
    end_idx: int,
    volume_index: int,
) -> dict[str, Any]:
    """构造 T_main 卷候选。"""
    start_chunk = summaries[start_idx]["chunk_index"]
    end_chunk = summaries[end_idx]["chunk_index"]
    # 主题词 = 起始摘要的关键词
    theme = _extract_dominant_keywords(summaries[start_idx]["summary"])
    stage = "发展"  # 占位，由 cluster_summaries 后处理更新

    return {
        "id": f"T_main_vol_{volume_index}",
        "name": f"剧情卷_{volume_index + 1}",
        "range": [start_chunk, end_chunk],
        "start_chunk": start_chunk,
        "end_chunk": end_chunk,
        "theme": theme,
        "stage": stage,
    }


def _make_module_candidate(
    summaries: list[dict],
    start_idx: int,
    end_idx: int,
    module_index: int,
) -> dict[str, Any]:
    """构造 E_module 候选。"""
    start_chunk = summaries[start_idx]["chunk_index"]
    end_chunk = summaries[end_idx]["chunk_index"]
    theme = _extract_dominant_keywords(summaries[start_idx]["summary"])

    return {
        "id": f"E_module_candidate_{module_index}",
        "name": f"剧情模块_{module_index + 1}",
        "range": [start_chunk, end_chunk],
        "start_chunk": start_chunk,
        "end_chunk": end_chunk,
        "theme": theme,
        "stage": "",
    }


def _extract_dominant_keywords(text: str, top_n: int = 3) -> str:
    """提取文本的主要关键词作为主题。"""
    keywords = _extract_keywords(text)
    if not keywords:
        return "未知主题"
    # 取前 top_n 个（已去停用词）
    sorted_kw = sorted(keywords, key=len, reverse=True)
    return "_".join(sorted_kw[:top_n])


def _deduplicate_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去重：合并重叠的 E_module 候选。"""
    if len(modules) <= 1:
        return modules

    # 按 start_chunk 排序
    sorted_modules = sorted(modules, key=lambda m: m["start_chunk"])
    deduplicated: list[dict[str, Any]] = [sorted_modules[0]]

    for mod in sorted_modules[1:]:
        last = deduplicated[-1]
        # 如果重叠超过 50%，合并
        overlap_start = max(last["start_chunk"], mod["start_chunk"])
        overlap_end = min(last["end_chunk"], mod["end_chunk"])
        if overlap_end >= overlap_start:
            overlap = overlap_end - overlap_start + 1
            last_len = last["end_chunk"] - last["start_chunk"] + 1
            if overlap / last_len > 0.5:
                # 合并：扩展 last 的范围
                last["end_chunk"] = max(last["end_chunk"], mod["end_chunk"])
                last["range"] = [last["start_chunk"], last["end_chunk"]]
                continue
        deduplicated.append(mod)

    return deduplicated


def _build_clusters_info(
    t_main_candidates: list[dict[str, Any]],
    module_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构建 clusters 信息（用于调试和可视化）。"""
    clusters: list[dict[str, Any]] = []

    for t_main in t_main_candidates:
        clusters.append({
            "type": "T_main",
            "entities": [t_main["id"]],
            "start_chunk": t_main["start_chunk"],
            "end_chunk": t_main["end_chunk"],
        })

    for mod in module_candidates:
        clusters.append({
            "type": "E_module",
            "entities": [mod["id"]],
            "start_chunk": mod["start_chunk"],
            "end_chunk": mod["end_chunk"],
        })

    return clusters
