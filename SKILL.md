# novel-to-graph-skill — 小说叙事语义分析技能

> **实施目的**：将小说文本转化为标准化知识库。

---

## 1. 技能定位

你的职责：读取 SKILL → 拆解输入文档 → 全局剧情模块划分 → 分配子智能体按模块批量提取 → 调用 tools → 写入 DB → 整合清洗 → 触发报表
所有注明LLM环节均由你直接或分配子智能体执行。

| 角色 | 职责 | 载体 |
|------|------|------|
| **prompts/**（执行说明） | 身份定义、处理规则、输出格式、处理流程、状态机、校验列表、关系建模（含人物小传）、Schema 规范 | Markdown 元提示词 |
| **tools/**（自动化工具） | 分块、文档蒸馏、摘要缓冲、语义聚类、骨架构建、定位、清洗、校验、过滤、量化、路由、合并、写入、坐标迁移、info压缩、图分析、人物小传、报表 | Python 函数 |

---

## 2. 主要任务流程

```
读取技能 → 拆解输入文档 → 全局剧情模块划分 → 按剧情模块批量提取 → 调用 tools 清洗校验 → 规范化写入 DB → LLM 整合清洗 → 触发报表
```

| 阶段 | 动作 | 载体 |
|------|------|------|
| **S1 读取技能** | 智能体加载本 SKILL.md，获取任务流程与子智能体编排规范 | AGENT |
| **S2 拆解输入文档** | 调用 `text_chunker.read_file` + `chunk_text`（v0.5.0 自适应 chunk 大小：默认 20K chars，通过 `detect_chunk_size()` 根据模型上下文自动选择 20K/8K/4K 三档；**v0.5.1 短章打包 `pack_chapters=True`（默认）**：连续短章贪心合并至接近 chunk_size，命中 20K 甜点，避免网文等均匀短章源逐章成块产出数千碎块）将 .txt 拆为 Chunk 列表 → 调用 `document_distiller.distill` 对每个 chunk 生成 Blueprint 摘要（100-300 字）→ 调用 `summary_buffer.SummaryBuffer` 滑动窗口缓冲摘要 | tools |
| **S2.5 增量压缩聚类+骨架构建** | 调用 `semantic_clusterer.cluster_summaries` 对摘要进行三重聚类（时序/场景/实体）→ 调用 `timeline_skeleton_builder.build_skeleton_incremental` 增量构建 T_main 卷 + E_module 实体 + 关系骨架（RAPTOR 范式，降级时回退 `build_skeleton` 一次性模式） | tools |
| **S3 按剧情模块批量提取** | 智能体读取 `prompts/extraction_meta_prompt.md`，按剧情模块批量分发子智能体：识别跨章节事件单元 → 填充 info（v0.5.0 差异化 Info Schema：事件四段/角色五段/地点物品规则体系各四段，500-1500字语义提炼）→ 提取其他实体（C/L/I/R），输出 JSON 字符串列表 | AGENT + prompts |
| **S4 调用 tools 清洗校验** | `json_cleaner.extract` → `schema_validator.validate`（v0.5.0 差异化校验：`validate_info_structure(entity_type, info)` 按实体类型选择 Schema）→ `har_refiner.refine_info`（HAR 自洽重抽，v0.5.0 按实体类型生成差异化 prompt）→ `info_compressor.compress_info`（>1500字触发）→ `low_value_filter.filter` | tools |
| **S5 规范化写入 DB** | `coords_migrator.migrate_coords`（旧数据迁移，按需）→ `quantifier.map_importance` → 智能体将字典转为 Entity/Relation 对象 → `id_router.route`（v0.5.0 角色 id 格式：`C_{name}__T_main_vol_{idx}`）→ `entity_merger.merge`（v0.5.0 多档案并行：角色按 `(name, type, t_main_volume)` 合并，不同卷不合并）→ `db_writer.write_all` | tools + AGENT |
| **S6 LLM 整合清洗** | 智能体读取 `prompts/relation_modeling.md` 与 `prompts/schema_specification.md`，对 DB 中数据进行最终整合：旧关系轴化转换 → **T_main/E_module 审查与重做**（v0.5.1：`evaluate_skeleton_quality` + `rebuild_skeleton`）→ T_branch 挂载校验 → S_topo 双向构建 → 出边裁剪 → 关系边索引化 → 零散节点聚类 → `graph_builder.build_evolves_to_relations`（v0.5.0：人物弧光链）→ **人物小传构建**（v0.5.1：`prepare_character_synthesis` + `create_synthesis_entity`）→ 冲突深度校验 | AGENT + prompts |
| **S7 触发报表** | `graph_builder.build` → `centrality_analyzer.analyze` → `community_detector.detect` → `bridges_finder.find` → `orphans_finder.find` → `stats_generator.generate` → `html_renderer.render` + `exporter.to_markdown`（v0.5.0 `group_by_character` 参数支持人物弧光总览导出）/`to_json` | tools |

### 2.1 S2.5 增量压缩聚类+骨架构建

在 S2 摘要缓冲完成后，通过增量压缩聚类（RAPTOR 范式）构建时序骨架，替代 v0.4.0 的章节标题抽样+LLM一次性划分方案。

**步骤1 — 语义聚类**:
- 调用 `semantic_clusterer.cluster_summaries(summaries, use_embedding=True)`
- 三重互补聚类策略：
  - **时序聚类**（阈值 0.55）：识别 T_main 卷边界
  - **场景聚类**（阈值 0.70）：按地点转移识别 E_module 边界
  - **实体聚类**（阈值 0.65）：按角色活跃期识别 E_module 边界
- Embedding 模型：`BAAI/bge-small-zh-v1.5` + cosine 相似度
- 降级路径：import 失败时使用 Jaccard 关键词重合度
- 输出：`{"t_main_candidates": [...], "module_candidates": [...]}`

**步骤2 — 增量骨架构建**:
- 调用 `timeline_skeleton_builder.build_skeleton_incremental(cluster_results)`
- 构建三层实体结构：
  - **T_main 实体**：剧情卷，5-20 个，每个含 `stage`（开篇/发展/转折/高潮/收束/尾声）
  - **E_module 实体**：剧情模块，每卷 ≤8 个，含 `start_chunk`/`end_chunk`/`theme`
  - **关系**：HAS_MODULE（卷→模块）+ T_main（卷间时序/模块间时序）
- 卷数 >20 时触发合并，卷数 <5 时触发扩展
- 输出：`Skeleton` 数据结构（t_main_volumes/e_modules/t_main_relations/has_module_relations/t_main_module_relations）

**步骤3 — 降级路径**:
- `build_skeleton_incremental` 失败时：自动回退 `build_skeleton(plot_modules)` 一次性模式
- 摘要不足时：生成占位摘要（基于 chunk 内容），降低骨架质量但不中断管线
- 降级标记：`skeleton_stats.fallback_used = True`

**异常处理**:
- 聚类结果为空：抛 ValueError（由调用方捕获）
- 卷数不在 [5, 20] 范围：由 `_adjust_volume_count` 自动修正
- E_module 数 >8/卷：由 `_merge_overflow_modules` 自动合并

### 2.2 S3 按剧情模块批量提取

S2.5 完成后，按剧情模块批量加载 chunks，分发子智能体执行跨章节事件识别和实体提取。

**步骤1 — 跨章节事件识别**:
- 按剧情模块批量加载对应 chunks
- LLM 任务：识别该模块内的跨章节事件单元（跨 ≥2 章节，具有目的性，包含完整起因-经过-结果）
- 原子动作（坐下、拿筷子、单次对话）不作为独立事件，仅作为 info 原材料
- 输出：每个模块的事件单元列表（含 event_id、chapter_range、purpose、result）

**步骤2 — 实体详情填充（v0.5.0 差异化 Info Schema）**:
- 对每个实体，加载对应 chunks
- LLM 任务：从 chunks 中归纳总结 info 字段
- info 要求：LLM 语义提炼（非原文摘录拼凑），按实体类型使用差异化段结构：

| 实体类型 | 段数 | 段结构 | 字数范围 |
|----------|------|--------|---------|
| event | 4 | 起因/经过/结果/模块定位 | 500-1500 |
| character | 5 | 身份背景/性格特征/能力体系/人际关系/人物弧光 | 500-1500 |
| location | 4 | 地理描述/政治经济/关联角色/剧情作用 | 400-1200 |
| item | 4 | 来源/功能/持有者变更/剧情作用 | 400-1200 |
| rule | 4 | 定义/约束条件/例外情况/剧情影响 | 400-1200 |
| system | 4 | 体系概述/层级结构/核心规则/剧情作用 | 400-1200 |

- 事件类型每段末尾必须附加 `[src:chunk_NNN]` 标记；非事件类型不强制
- 超过字数上限时：触发 `info_compressor.compress_info` 压缩
- 不足字数下限时：触发 HAR 重抽

**步骤3 — 其他实体提取**:
- 按剧情模块批量提取角色(C)、地点(L)、物品(I)、规则(R)实体
- 每个实体分配五维坐标（T/L/C/E/R 唯一值）
- 角色实体 id 格式：`C_{name}__T_main_vol_{idx}`（v0.5.0 多档案并行）
- 通过关系边（R_strong/S_topo/T_branch）建立与剧情模块的索引

**输出结果**: 完整实体列表（E_module + E_event + C + L + I + R）+ 关系列表（含 evolves_to 人物弧光链）。

---

## 3. 子智能体编排规范

### 3.1 增量压缩聚类+骨架构建（S2.5 阶段）

| 项 | 规范 |
|----|------|
| **输入** | 摘要列表（来自 `summary_buffer` 或 `document_distiller` 输出） |
| **任务** | 调用 `semantic_clusterer.cluster_summaries` 进行三重聚类 → 调用 `timeline_skeleton_builder.build_skeleton_incremental` 增量构建骨架 |
| **输出** | `Skeleton` 数据结构（t_main_volumes/e_modules/关系） |
| **调用次数** | 1 次（全量摘要输入，增量压缩输出） |
| **异常降级** | 增量压缩失败时回退 `build_skeleton` 一次性模式 |

### 3.2 按模块批量提取子智能体（S3 阶段）

| 项 | 规范 |
|----|------|
| **输入** | 单个剧情模块 + 对应 chunks 内容 + `extraction_meta_prompt.md` 作为 system prompt |
| **任务** | 按 prompts 中的身份定义、处理规则、输出格式（v0.5.0 差异化 Info Schema）、处理流程、状态机执行语义抽取：跨章节事件识别 → info 填充 → 其他实体提取 |
| **输出** | 符合 `schema_specification.md` 的 JSON 对象列表（含五维坐标唯一值） |
| **并行度** | 多剧情模块可并行分发，子智能体间无状态共享 |
| **规模约束** | info 字段按实体类型使用差异化段结构（事件四段/角色五段/其他四段）；事件必须为跨章节完整单元（非原子动作）；角色实体 id 格式 `C_{name}__T_main_vol_{idx}` |

### 3.3 整合清洗子智能体（S6 阶段 · 图遍历审查）

| 项 | 规范 |
|----|------|
| **输入** | DB 中已写入的 Entity/Relation 全集 + `relation_modeling.md` + `schema_specification.md` |
| **任务** | 数据完整录入图数据库后，由 LLM 进行按剧情模块批量图遍历审查和质量评估 |
| **输出** | 更新后的 DB 记录（UPSERT 语义） |

**S6 图遍历审查子任务**（按序执行）：

1. **旧关系轴化转换** — 将旧7种关系类型映射为7种轴关系类型（located_in/belongs_to→S_topo入边, participates_in→T_branch, causes→A_causal, evolves_to→evolves_to（v0.5.0 独立类型）, relates_to/references→R_strong）
2. **T_main/E_module 审查与重做**（v0.5.1 增强）— 调用 `graph_builder.evaluate_skeleton_quality` 评估骨架质量（T_main 卷数 / E_module 颗粒度 / T_branch 覆盖率三维度）。若 verdict=rebuild，调用 `graph_builder.rebuild_skeleton` 用提高后的阈值（0.70/0.85/0.80）重新聚类+构建骨架，然后重建 T_branch 挂载。重做失败时回退原始骨架
3. **T_branch 挂载校验** — 确认每个 E_event 通过 T_branch 挂载到所属 E_module（若步骤 2 触发重做，需重新挂载）
4. **S_topo 双向构建** — 实体→L 入边（地理归属，实体出边 ≤3）+ L→E_module/E_event 出边（空间索引，地点出边 ≤20）
5. **出边裁剪** — 按扇出上限裁剪（剧情模块 T_branch ≤20 + R_strong ≤30；角色 ≤5；事件 ≤3；地点仅 S_topo 出边 ≤20），保留 strong 优先
6. **关系边索引化** — 校验关系 description ≤50 字推荐，>100 字拒绝入库（详见 `relation_modeling.md` §6）
7. **零散节点聚类** — 孤儿节点和微型节点聚类合并到轴上；碎片事件合并到所属跨章节事件单元
8. **人物弧光链构建** — 调用 `graph_builder.build_evolves_to_relations` 为同一角色在不同卷的档案创建 evolves_to 关系链
9. **人物小传构建**（v0.5.1 新增）— 调用 `character_synthesizer.prepare_character_synthesis` 收集各卷角色档案 → LLM 按 5 段结构（身份概述/性格演变/能力成长/关系网络/人物弧光）生成人物小传 → 调用 `character_synthesizer.create_synthesis_entity` 创建 `C_{name}__synthesis` 实体写入 DB
10. **冲突深度校验** — 对 `conflict_detected=true` 的记录执行深度图遍历消解

### 3.4 报表触发子智能体（S7 阶段）

| 项 | 规范 |
|----|------|
| **输入** | 整合清洗后的 DB |
| **任务** | 调用图分析工具组生成报表与导出文件 |
| **输出** | report.html / report.md / report.json |

---

## 4. 目录路由

```
novel-to-graph-skill/
├── SKILL.md                          # 本文件（入口规范）
├── prompts/                          # 执行说明元提示词
│   ├── extraction_meta_prompt.md     # 主元提示词（v0.5.0 差异化 Info Schema；v0.5.1 无 S3 变更）
│   ├── relation_modeling.md          # 关系建模补充规则（v0.5.0 含 evolves_to；v0.5.1 §9 骨架审查+人物小传）
│   ├── schema_specification.md       # 输出 JSON Schema 规范（v0.5.0 按类型区分；v0.5.1 §4.8 人物小传 Schema）
│   └── plot_module_prompt.md         # [legacy] S2.5 剧情模块划分提示词（v0.4.0 方案，已被增量聚类替代）
├── tools/                            # 工具函数（无状态 Python）
│   ├── text_chunker.py               # 文件读取 + 章节检测 + 分块（v0.5.0 自适应 chunk）
│   ├── document_distiller.py         # 文档蒸馏：chunk → Blueprint 摘要（100-300字）
│   ├── summary_buffer.py             # 滑动窗口缓冲（窗口50，flush间隔10）
│   ├── semantic_clusterer.py         # 语义聚类（时序/场景/实体三重聚类）
│   ├── timeline_skeleton_builder.py  # 时序骨架构建（增量压缩 + 一次性降级）
│   ├── chapter_title_sampler.py      # [legacy] 章节标题抽样（v0.4.0 方案，已被增量聚类替代）
│   ├── rule_locator.py               # 规则定位候选实体
│   ├── json_cleaner.py               # LLM 输出 JSON 清洗
│   ├── schema_validator.py           # Schema 校验（v0.5.0 差异化：按实体类型选择 Schema）
│   ├── har_refiner.py                # HAR 自洽重抽（v0.5.0 按实体类型生成差异化 prompt）
│   ├── info_compressor.py            # info 超长压缩
│   ├── low_value_filter.py           # 低价值记录过滤
│   ├── coords_migrator.py            # 旧六维→新五维坐标迁移
│   ├── quantifier.py                 # 定性→定量映射
│   ├── id_router.py                  # 实体 ID 路由（v0.5.0 角色 id 格式 C_{name}__T_main_vol_{idx}）
│   ├── entity_merger.py              # 实体合并去重（v0.5.0 多档案并行：角色按卷合并）
│   ├── db_writer.py                  # SQLite 写入
│   ├── graph_builder.py              # NetworkX 图构建（v0.5.0 含 evolves_to 关系）
│   ├── centrality_analyzer.py        # 中心性分析
│   ├── community_detector.py         # 社群检测
│   ├── bridges_finder.py             # 桥接节点识别
│   ├── orphans_finder.py             # 孤立实体检测
│   ├── stats_generator.py            # 图统计报告
│   ├── html_renderer.py              # HTML 报表渲染
│   ├── character_synthesizer.py      # 人物小传构建（v0.5.1 新增）
│   ├── exporter.py                   # MD/JSON 导出（v0.5.0 group_by_character 参数）
├── templates/                        # schema.sql + report.html.j2
├── static/                           # report.js
└── tests/                            # 测试用例（v0.5.0: test_chunk_adaptive/test_info_schema/test_multi_profile；v0.5.1: test_cluster_thresholds/test_skeleton_quality/test_rebuild_skeleton/test_character_synthesizer/test_synthesis_entity）
```

### prompts 路由优先级

| 阶段 | 必读 | 选读 |
|------|------|------|
| S2.5 增量聚类 | —（纯工具，无 LLM 调用） | — |
| S3 按模块批量提取 | `extraction_meta_prompt.md` | `schema_specification.md`（字段速查） |
| S6 整合清洗 | `relation_modeling.md` + `schema_specification.md` | `extraction_meta_prompt.md` §7 校验列表 |

### v0.5.0/v0.5.1 新增/变更工具速查

| 工具 | 文件 | 阶段 | 职责 |
|------|------|------|------|
| `detect_chunk_size` | `tools/text_chunker.py` | S2 | 自适应 chunk 大小检测（三档 20K/8K/4K） |
| `document_distiller.distill` | `tools/document_distiller.py` | S2 | 文档蒸馏：chunk → Blueprint 摘要（场景/行动/变动/因果） |
| `SummaryBuffer` | `tools/summary_buffer.py` | S2 | 滑动窗口缓冲（窗口50，flush间隔10，FIFO溢出丢弃） |
| `semantic_clusterer.cluster_summaries` | `tools/semantic_clusterer.py` | S2.5 | 三重语义聚类（时序0.55/场景0.70/实体0.65） |
| `build_skeleton_incremental` | `tools/timeline_skeleton_builder.py` | S2.5 | 增量压缩构建 T_main + E_module 骨架 |
| `get_info_schema` | `tools/models.py` | S3/S4 | 按实体类型返回差异化 Info Schema |
| `validate_info_structure` | `tools/schema_validator.py` | S4 | 签名变更：新增 `entity_type` 参数，按类型校验 |
| `generate_har_prompt` | `tools/har_refiner.py` | S4 | 按实体类型生成差异化 HAR 重抽 prompt |
| `build_evolves_to_relations` | `tools/graph_builder.py` | S6 | 构建人物弧光关系链（evolves_to） |
| `merge` / `_merge_entities` | `tools/entity_merger.py` | S5 | 合并键变更：角色按 `(name, type, t_main_volume)` 合并 |
| `evaluate_skeleton_quality` | `tools/graph_builder.py` | S6 | 骨架质量评估（T_main卷数/E_module颗粒度/T_branch覆盖率） |
| `rebuild_skeleton` | `tools/graph_builder.py` | S6 | 用提高后的阈值重建骨架（降级返回原始骨架） |
| `prepare_character_synthesis` | `tools/character_synthesizer.py` | S6 | 收集各卷角色档案，按名分组排序 |
| `create_synthesis_entity` | `tools/character_synthesizer.py` | S6 | 创建 `C_{name}__synthesis` 人物小传实体 |

---

## 5. v0.4.0 → v0.5.1 改进摘要

### 5.0 v0.5.1 补丁改进（短章打包 · 实证甜点）

| # | 改进点 | v0.5.0 问题 | v0.5.1 方案 | 影响阶段 |
|---|--------|------------|------------|---------|
| 1 | 短章打包 (`pack_chapters`) | `DEFAULT_CHUNK_SIZE=20K` 仅是"上限"；均匀短章源（网文每章 ~2.4K 字）逐章成块，实测全职法师 763万字 → **3136 碎块**，自适应 chunk 大小完全失效 | `chunk_text(pack_chapters=True)` 默认开启：连续短章贪心合并至接近 chunk_size。全职法师全本 → **414 块（均值 18.4K 字）**，正中 20K 甜点 | S2 |

> **实证依据**（`07_子项目代码/LLM对话作品卡/全职法师/novel_analysis/v05/experiment_report.md`）：同一 100K 窗口下，20K 切片抽取密度 1.35 rec/Kchar、字数达标率 94.8%、平均 662 字，均为 8K/20K/100K 三档最优；100K 单遍存在约 45% 尾部注意力衰减。故将 20K 打包固化为生产默认。

### 5.1 v0.5.0 新增改进

| # | 改进点 | v0.4.1 问题 | v0.5.0 方案 | 影响阶段 |
|---|--------|------------|------------|---------|
| 1 | 自适应 Chunk 大小 | 8K chars 固定，system_prompt(18K) 是 chunk 的 2.3 倍，浪费 token | 默认 20K chars，三档可调（20K/8K/4K），`detect_chunk_size()` 根据模型上下文自动选择 | S1/S2 |
| 2 | 差异化 Info Schema | 所有实体类型统一四段叙事结构，对角色/地点/物品/规则/体系信息扭曲 | 6 种实体类型各有独立段结构，事件类型保留四段向后兼容，`validate_info_structure(entity_type, info)` 按类型校验 | S3/S4 |
| 3 | 多档案并行实体策略 | 实体档案仅首次出现时归纳，后续仅做 info 字符串拼接，不随人物弧光更新 | 角色实体按 `C_name + T_main_vol` 双关键字拆分，`evolves_to` 关系串联人物弧光，合并器按 `(name, type, t_main_volume)` 合并 | S5/S6/S7 |

### 5.2 v0.4.0 改进（历史基线）

| # | 改进点 | v0.3.0 问题 | v0.4.0 方案 | 影响阶段 |
|---|--------|------------|------------|---------|
| 1 | 全局剧情模块划分 | 11,151事件/3,038散乱T值，无全局视角 | 新增 S2.5 阶段：章节标题抽样→LLM划分→T_main骨架 | S2→S3 之间 |
| 2 | T类语义重构 | T_main 存具体事件串联（5,938条），主轴被淹没 | T_main 变纯索引（仅 E_module→E_module）；事件通过 T_branch 挂载 | S3/S4/S5/S6 |
| 3 | 五维坐标唯一值化 | coords.C 存4个角色列表，坐标与关系混淆 | 六维→五维（移除K）；每维度从多值列表改为唯一值 | S3/S4/S5 |
| 4 | info字段质量强化 | 平均235字，达标率1.5%，原文切片 | info 必须 LLM 语义提炼；500-1500字；>1500字压缩 | S3/S4 |
| 5 | S_topo 双向 | S_topo 仅单向归属，地点不扇出 | 入边（实体→L）+出边（L→E_module/E_event），空间关系升为平行主轴 | S6 |
| 6 | 关系边仅作索引 | 详情分散到关系 description（200+字） | description ≤50字推荐/≤100字上限；节点详情内聚于 info | S3/S4/S6 |

**核心设计哲学**：坐标=位置（唯一值），关系=连接（多值边）。先建立全局骨架，再填充局部内容，最后保证质量。

---

## 6. 锚定文档

| 文档 | 路径 |
|------|------|
| 系统全景需求定义书 | `02_策划文档/novel_analysis_skill/v0.5.1_升级/系统全景需求定义书.md` |
| L0 项目定位 | `02_策划文档/novel_analysis_skill/v0.5.1_升级/00_技术锚定/L0_项目定位与架构概览.md` |
| L1 模块边界 | `02_策划文档/novel_analysis_skill/v0.5.1_升级/00_技术锚定/L1_模块边界与需求索引.md` |
| L2 数据模型 | `02_策划文档/novel_analysis_skill/v0.5.1_升级/00_技术锚定/L2_数据模型与核心算法.md` |
| L3 接口契约 | `02_策划文档/novel_analysis_skill/v0.5.1_升级/00_技术锚定/L3_接口契约与约束.md` |
| 构造计划 | `02_策划文档/novel_analysis_skill/v0.5.1_升级/tasks/plan.md` |
| 论文 | `08_记忆数据/knowledge-base/skills/novel-to-graph-skill/论文_信息提取压缩结构化聚类拓扑_v1.0.md` |

---

**版本**: 0.5.1 | **状态**: ✅ 已完成 | **更新**: 2026-07-14
