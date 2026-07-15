# novel-analysis-skill

> 小说知识图谱构建工具包  v0.5.1
> S1-S7 七阶段管线 + 骨架审查与重做 + 人物小传构建

## 简介

novel-analysis-skill 是一个用于从长篇小说文本中提取结构化知识图谱的工具包。采用 S1-S7 七阶段管线，将原始小说文本转化为基于五维坐标（T/L/C/E/R）和轴关系模型的知识图谱，支持跨章节事件识别、角色弧光追踪、骨架质量审查与人物小传构建。

## 核心特性

- **S1 文本分块**: 自适应 chunk 大小（20K/8K/4K 三档映射，根据模型上下文窗口自动选择）
- **S2 文档蒸馏**: LLM 语义压缩，生成 distill 摘要缓冲
- **S2.5 语义聚类**: RAPTOR 范式增量压缩聚类，三重聚类（时序 0.55/场景 0.70/实体 0.65）
- **S3 跨章节事件识别**: LLM 抽取跨章节事件单元 + 五维坐标 + 轴关系 + 差异化 Info Schema（6 种实体类型）
- **S4 溯源校验**: [src:chunk_NNN] 标记验证，确保 info 可溯源
- **S5 入库**: schema 校验 + SQLite 持久化 + WAL 模式
- **S6 LLM 整合清洗**: 轴化处理 + 骨架审查与重做 + 人物弧光链 + 人物小传构建 + 冲突深度校验
- **S7 图分析报表**: 中心性分析 + 社区检测 + 桥接节点 + 孤儿节点 + HTML 报告

## v0.5.1 新特性

### B1 骨架审查与重做
- 三维度评估骨架质量：T_main 卷数 / E_module 颗粒度 / T_branch 覆盖率
- verdict=pass|rebuild 自动决策
- rebuild_skeleton 用提高后的阈值（0.70/0.85/0.80）重新聚类+构建骨架
- 重做失败时降级返回原始骨架

### B2 人物小传构建
- 为出现在 >=2 个 T_main 卷的角色生成统合性人物小传
- 5 段结构：身份概述 / 性格演变 / 能力成长 / 关系网络 / 人物弧光
- 800-2000 字，LLM 语义提炼
- synthesis 实体（C_{name}__synthesis）写入 DB

## 目录结构

`
novel-analysis-skill/
 SKILL.md              # 技能入口文档（七阶段管线总览）
 prompts/              # LLM 提示词（4 个文件）
    extraction_meta_prompt.md     # S3 主元提示词
    relation_modeling.md          # S6 关系建模规则
    schema_specification.md       # JSON Schema 规范
    plot_module_prompt.md         # [LEGACY] v0.4.0 剧情模块划分
 tools/                # Python 工具函数（27 个模块）
    models.py                     # 数据模型 + 配置常量
    text_chunker.py               # S1 文本分块
    document_distiller.py         # S2 文档蒸馏
    semantic_clusterer.py         # S2.5 语义聚类
    timeline_skeleton_builder.py  # S2.5 时序骨架构建
    schema_validator.py           # S4/S5 校验
    db_writer.py                  # S5 入库
    graph_builder.py              # S6 图构建 + 骨架审查/重做
    character_synthesizer.py      # S6 人物小传构建
    ...                           # 其他工具
 templates/            # HTML/SQL 模板
 static/               # 静态资源（JS）
 tests/                # 测试用例
`

## 架构设计

### 双轨架构
- **tools/**: 纯 Python 工具函数，不调用 LLM、不进行智能体编排、不提供 CLI/HTTP API
- **prompts/**: 执行说明文本，由智能体读取后作为调用 LLM 的 system prompt

### 五维坐标模型

| 维度 | 说明 | 示例 |
|------|------|------|
| T | 所属剧情模块ID | E_module_博城篇 |
| L | 主场景地点ID | L_博城 |
| C | 主体角色ID | C_莫凡 |
| E | 所属事件单元ID | E_觉醒仪式 |
| R | 规则子类 | R_power |

### 轴关系类型（7种）
- T_main: 时序主轴（E_module 间）
- T_branch: 时序分支（E_module -> E_event）
- S_topo: 空间拓扑轴（双向）
- A_causal: 因果辅轴
- A_arc: 角色弧光辅轴
- evolves_to: 角色演化轴（v0.5.0）
- R_strong: 强关联索引

## 使用方式

本工具包为 skill 架构，由智能体读取 SKILL.md 和 prompts/ 中的执行说明后按需调用 tools/ 中的工具函数。

`python
# 示例：S1 文本分块
from tools.text_chunker import chunk_text
chunks = chunk_text(text, model_ctx_tokens=20000)

# 示例：S2.5 语义聚类
from tools.semantic_clusterer import cluster_summaries
clusters = cluster_summaries(summaries, thresholds={'timeline': 0.55, 'scene': 0.70, 'entity': 0.65})

# 示例：S6 骨架审查
from tools.graph_builder import evaluate_skeleton_quality, rebuild_skeleton
result = evaluate_skeleton_quality(skeleton)
if result['verdict'] == 'rebuild':
    new_skeleton = rebuild_skeleton(summaries, skeleton)
`

## 版本历史

| 版本 | 主要变更 |
|------|----------|
| v0.5.1 | 骨架审查与重做 + 人物小传构建 |
| v0.5.0 | 差异化 Info Schema + 多档案并行 + evolves_to + RAPTOR 聚类 |
| v0.4.0 | 五维坐标（移除K）+ 轴关系模型 + E_module 子类型 |
| v0.3.0 | 六维坐标 + 关系类型初步定义 |

## 技术栈

- Python 3.12+
- SQLite（WAL 模式）
- BAAI/bge-small-zh-v1.5（embedding，Jaccard 兜底）
- Jinja2（HTML 模板）

## 许可证

MIT
