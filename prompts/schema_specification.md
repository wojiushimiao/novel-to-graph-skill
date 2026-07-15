# 子智能体 输出 JSON Schema 规范

> 定义子智能体 应输出的 JSON Schema。字段必填性与枚举值校验详见 `extraction_meta_prompt.md` §7。
> S3 跨章节事件识别与 S6 整合清洗阶段必读。
> v0.4.0: 五维坐标唯一值化（移除K）；E_module 子类型；info 校验规则；关系 description 契约。
> v0.5.0: 差异化 Info Schema（§4.1，按实体类型区分段结构和字数）；角色 id 格式 `C_{name}__T_main_vol_{idx}`。
> v0.5.1: 新增 §4.8 人物小传 Schema（character_synthesis，5 段结构，800-2000 字）。

---

## 1. 顶层 Schema

```json
{
  "event_id": "string (必填, 非空, 格式 E_<核心事件简称>)",
  "stitch": {
    "sigma": "string (必填, 非空, 主题范围)",
    "epsilon": "string (必填, 非空, 事件类型)",
    "kappa": "string (必填, 非空, 实体大类)"
  },
  "coords": {
    "T": "string (必填, 所属剧情模块ID, 唯一值)",
    "L": "string (必填, 主场景地点ID, 唯一值)",
    "C": "string (必填, 主体角色ID, 唯一值)",
    "E": "string (必填, 所属事件单元ID, 唯一值; 事件本身为空)",
    "R": "string (必填, 规则子类, 唯一值; 无则空字符串)"
  },
  "importance": "string (必填, 枚举: high|medium|low)",
  "delta_update": {
    "target_entity_id": "string (必填, 非空, 格式 {type[0].upper()}_{name})",
    "updated_fields": {
      "info": "string (必填, 非空, 500-1500 字, LLM语义提炼)",
      "new_wiki_relations": [
        {
          "target": "string (必填, 目标实体名称或 ID)",
          "type": "string (必填, 6 种轴关系之一: T_main|T_branch|S_topo|A_causal|A_arc|R_strong)",
          "strength": "string (必填, 枚举: strong|weak)",
          "description": "string (选填, ≤50字推荐, ≤100字上限, 一句话索引说明)"
        }
      ]
    },
    "conflict_detected": "boolean (必填)",
    "conflict_note": "string (条件必填, 若 conflict_detected=true 则必填非空)"
  }
}
```

---

## 2. 五维坐标 Schema（v0.4.0 核心变更）

### 2.1 坐标定义（六维→五维）

旧六维: T/L/C/E/K/R（多值列表）
新五维: T/L/C/E/R（唯一值）

| 维度 | 类型 | 唯一值 | 说明 | 示例 |
|------|------|--------|------|------|
| T | string | 所属剧情模块ID | 实体在时序上的模块归属 | "E_module_博城篇" |
| L | string | 主场景地点ID | 实体的主要发生地点 | "L_水兰中学" |
| C | string | 主体角色ID | 事件的主导者（事件本身为空） | "C_莫凡" |
| E | string | 所属事件单元ID | 实体所属的事件单元 | "E_觉醒仪式" |
| R | string | 规则子类 | 涉及的规则类型（无则空） | "R_power" |

**坐标-关系分离原则**：
- 坐标 = 位置（唯一值），定位实体在五维空间中的归属
- 关系 = 连接（多值边），通过关系类型边表达实体间关联
- 涉及的多个角色通过 R_strong 关系边表达，不放入 coords.C 列表

### 2.2 K 维度移除声明

**K 维度（关联主题）已废弃**：
- v0.3.0 中 K 维度定义为关联主题列表，实测变为散乱关键词
- v0.4.0 移除 K 维度，主题分类功能由剧情模块（E_module）承担
- coords 中不允许出现 K 键（校验错误码: E_K_DIMENSION_FOUND）

### 2.3 coords 字段结构变更

| 项 | v0.3.0（旧） | v0.4.0（新） |
|----|-------------|-------------|
| 维度数 | 6 维（T/L/C/E/K/R） | 5 维（T/L/C/E/R） |
| 值类型 | 多值列表（string[]） | 唯一值（string） |
| R 维度 | 字典 {subtype, rule_name} | 子类字符串（如 "R_power"） |
| K 维度 | 主题列表 | 已移除 |

**校验规则**（详见 `schema_validator.validate_coords_unique`）：
- T/L/C/E/R 每维度值必须是 string 类型
- 不允许出现 list/set/tuple/dict 类型值
- 不允许出现 K 维度键
- 缺失维度视为空字符串 ""，校验通过

---

## 3. 实体 ID 格式

`{type[0].upper()}_{name}`，示例：

| 类型 | ID 格式 | 示例 |
|------|---------|------|
| 剧情模块 (E_module) | `E_module_<name>` | `E_module_博城篇` |
| 角色 (Character) | `C_<name>` | `C_莫凡` |
| 地点 (Location) | `L_<name>` | `L_博城` |
| 事件 (Event) | `E_<name>` | `E_觉醒仪式` |
| 物品 (Item) | `I_<name>` | `I_雷印` |
| 规则 (Rule) | `R_<subtype>_<name>` | `R_power_元素系觉醒规则` |
| 系统 (System) | `S_<name>` | `S_魔法系统` |

### E_module 子类型定义（v0.4.0 新增）

| 属性 | 说明 |
|------|------|
| **类型名** | E_module |
| **ID 前缀** | E_module_ |
| **职责** | 剧情模块实体，作为时序主轴节点和信息集群 |
| **coords.T** | 自身 ID（E_module 的 T 坐标为自身） |
| **必有关系** | 每个 E_module 至少一条 T_main 出边或入边 |
| **T_main 约束** | T_main 仅存在于 E_module 之间 |
| **来源** | S2.5 阶段由 LLM 划分，timeline_skeleton_builder 构建 |

---

## 4. info 校验规则（v0.5.0 差异化）

### 4.1 差异化校验规则（v0.5.0）

info 字段的校验规则因实体类型而异：

| 实体类型 | 段结构 | src标记 | 字数范围 |
|----------|--------|---------|---------|
| event | 四段 | 强制 | 500-1500 |
| character | 五段 | 可选 | 500-1500 |
| location | 四段 | 可选 | 400-1200 |
| item | 四段 | 可选 | 400-1200 |
| rule | 四段 | 可选 | 400-1200 |
| system | 四段 | 可选 | 400-1200 |

非事件类型不强制 [src:chunk_NNN] 标记，因为信息来自多处综合而非单一 chunk。

### 4.2 字数要求（v0.5.0 差异化）

info 字数要求按实体类型差异化（见 §4.1）：

| 实体类型 | 字数范围 | 超长处理 | 过短处理 |
|----------|---------|---------|---------|
| event | 500-1500 | >1500 压缩至 1200-1500 | <500 触发 HAR 重抽 |
| character | 500-1500 | >1500 压缩至 1200-1500 | <500 触发 HAR 重抽 |
| location | 400-1200 | >1200 压缩 | <400 触发 HAR 重抽 |
| item | 400-1200 | >1200 压缩 | <400 触发 HAR 重抽 |
| rule | 400-1200 | >1200 压缩 | <400 触发 HAR 重抽 |
| system | 400-1200 | >1200 压缩 | <400 触发 HAR 重抽 |

校验方式: `schema_validator.validate_info_length(entity_type, info)`

### 4.3 结构化四段格式（事件类型 · v0.4.1 强制）

**说明**：v0.5.0 起，四段结构仅适用于事件（event）类型。其他实体类型使用各自对应的差异化 Schema（见 §4.1）。

info 字段必须按以下四段结构输出，每段以段首标记开头：

```
【起因】（≥100字）：事件触发的根本原因，包含背景上下文。[src:chunk_NNN]
【经过】（≥200字）：核心过程概括，按时间顺序组织，含关键转折点。[src:chunk_NNN]
【结果】（≥100字）：事件结局和对后续的影响。[src:chunk_NNN]
【模块定位】（≥100字）：事件在所属剧情模块中的位置和作用。[src:chunk_NNN]
```

**四段结构校验**（`schema_validator.validate_info_structure`）：
- 四段标记（`【起因】`/`【经过】`/`【结果】`/`【模块定位】`）必须全部存在
- 缺段或段首标记缺失 → 返回 (False, "missing_section: <section_name>")
- 段内字数不足 → 返回 (False, "section_too_short: <section_name>")

### 4.4 过程校验标记 `[src:chunk_NNN]`（事件类型 · v0.4.1 新增）

**必填**：事件类型每段末尾必须附加 `[src:chunk_NNN]` 标记。非事件类型不强制此标记。

| 属性 | 说明 |
|------|------|
| 格式 | `[src:chunk_<数字>]` 或 `[src:chunk_<数字>-<数字>]`（跨 chunk） |
| 用途 | S4 溯源校验，定位 info 内容来源 |
| 剥离时机 | S5 入库前由 `schema_validator.strip_src_markers` 强制剥离 |
| 畸形判定 | `[src:chunk_]`（空索引）、`[src:chunk_abc]`（非数字）视为缺失 |
| 校验函数 | `schema_validator.validate_src_marker` |

**校验返回值**：
- (True, "pass")：四段均含合法标记
- (False, "missing_marker: <section_name>")：某段缺失标记
- (False, "malformed_marker: <marker>")：标记格式畸形

### 4.5 质量要求

- **LLM 语义提炼**：必须是 LLM 归纳总结，非原文摘录拼凑
- **禁止原文切片**：不得直接摘录原文句子
- **四段完整**：缺段或段内字数不足均触发 HAR 重抽
- **过程标记必填**：每段末尾必须有 `[src:chunk_NNN]`，S5 剥离

### 4.6 质量检测启发式

- 句号密度：正常语义提炼的句号密度 ∈ [0.01, 0.05]
- 对话标点（""「」）：原文切片通常对话标点密度 > 0.05
- 超过阈值标记为疑似原文切片，触发 HAR 重抽

### 4.7 HAR 失败标记（v0.4.1 新增）

HAR 重抽 3 次仍不达标的条目，在 `delta_update.updated_fields.hint_tags` 字段写入 `"HAR_FAILED"` 标记：

```json
{
  "delta_update": {
    "updated_fields": {
      "info": "<最佳重抽结果（即使不达标）>",
      "new_wiki_relations": [...],
      "hint_tags": ["HAR_FAILED"]
    }
  },
  "importance": "low"  // HAR 失败自动降级
}
```

`hint_tags` 字段为 `list[str]` 类型，已存在于 v0.4.0 schema，无需扩展。HAR 失败的条目仍入库，但 importance 降级为 low，供后续审查追踪。

### 4.8 人物小传 Schema（character_synthesis · v0.5.1 新增）

**说明**: 人物小传是出现在 ≥2 个 T_main 卷的角色的统合性简介，由 LLM 在 S6 步骤 9 中生成。

**Schema 定义**:

| 段名 | 最低字数 | 说明 |
|------|---------|------|
| 身份概述 | 150 | 角色基本身份、背景、定位 |
| 性格演变 | 150 | 性格随卷数的演变轨迹 |
| 能力成长 | 150 | 能力体系的成长路径 |
| 关系网络 | 150 | 核心人际关系及变化 |
| 人物弧光 | 200 | 完整人物弧光总结 |

**总字数**: 800-2000 字

**实体格式**:
- id: `C_{name}__synthesis`（如 `C_莫凡__synthesis`）
- type: `character`
- coords.T: `synthesis`（不绑定特定卷）
- coords.C: 角色名
- importance: `high`
- detail_info: `{"volumes_covered": [int], "source_profiles": [str]}`

**与 per-volume 档案的区别**:
- per-volume 档案（`C_莫凡__T_main_vol_0`）记录特定卷中的角色状态
- synthesis 档案（`C_莫凡__synthesis`）是跨卷统合，提供全局视角
- synthesis 通过 `detail_info.source_profiles` 索引到各卷档案

---

## 5. 关系 description 字段契约（v0.4.0 微调新增）

### 5.1 核心原则

**关系边是"指针+门控"，不是"内容容器"**。详细信息只存在于节点 info 中。

| 约束 | 说明 | 校验方式 |
|------|------|---------|
| 字数上限 | ≤ 100 字（硬限制） | schema_validator.validate_relation_desc_length |
| 推荐字数 | ≤ 50 字一句话 | 质量检测（启发式） |
| 内容性质 | 索引说明，非详情 | LLM 重抽（疑似详情分散时） |
| 空值允许 | 可为空字符串 | 仅作指针 |

### 5.2 校验返回值语义

- `(True, "pass")`：字数 ≤ 50，符合推荐
- `(True, "warn_suspicious")`：字数 ∈ (50, 100]，标记疑似详情分散
- `(False, "reject_too_long")`：字数 > 100，拒绝入库

### 5.3 禁止内容

关系 description 不得承载以下内容（必须内聚于实体 info 字段）：
- 起因经过结果
- 人物关系背景
- 事件详情
- 规则定义

---

## 6. delta_update 结构详解

### 6.1 updated_fields.info（语义提炼，非原文摘录）

**必须是 LLM 语义提炼的摘要**，禁止原文摘录拼凑。字数控制在 500-1500 字。

**摘要提炼要求**：
- 必须是对情节的**语义提炼**，用分析性语言概括核心事实
- 必须包含：核心目的与起因 + 关键经过归纳 + 结果与影响 + 与剧情模块关系定位
- 关联事件应聚合为统一描述（起因/经过/结果/各方反应）
- 禁止堆砌原文对话或描写
- 禁止随机摘录原文句子拼凑

正确示例（提炼摘要）：
- `"莫凡在第4章觉醒仪式中觉醒雷系，成为罕见的双系法师。觉醒过程中雷印显现，引发全场震惊。此事件改变了莫凡的能力轨迹，使其从普通学徒跃升为双系法师。觉醒仪式由博城魔法学院主持，莫凡在众目睽睽之下完成觉醒，雷系能力的显现打破了单系觉醒的常规。此事件为莫凡角色弧光的关键转折点，时序归属博城篇模块。"`

错误示例：
- `"莫凡说道：'我竟然觉醒了雷系！'全场一片寂静。张小候瞪大了眼睛。"`（**原文摘录拼凑，禁止**）
- `"莫凡走上台。魔法师念了咒语。光芒闪过。莫凡看到了雷印。"`（**原子动作堆砌，应聚合为事件单元摘要**）

### 6.2 updated_fields.new_wiki_relations

新增的 wiki 关系列表。每个关系包含 `target`、`type`、`strength`、`description` 四字段。

示例：
```json
[
  {"target": "L_博城", "type": "S_topo", "strength": "strong", "description": "地理归属"},
  {"target": "E_module_博城篇", "type": "T_branch", "strength": "strong", "description": "所属模块"},
  {"target": "I_雷印", "type": "R_strong", "strength": "strong", "description": "专属武器"},
  {"target": "C_张小候", "type": "R_strong", "strength": "strong", "description": "同班挚友"}
]
```

### 6.3 conflict_detected 与 conflict_note（疑似冲突即上报）

**疑似冲突即上报机制**：不要求 LLM 完整举证，简述违和点即可，由 S6 阶段深度图遍历校验。

- `conflict_detected=false, conflict_note=""`：无冲突，与候选上下文一致且无直觉违和
- `conflict_detected=true, conflict_note="原文描述莫凡觉醒火系，但前文提及他已觉醒雷系，存在矛盾"`：确认冲突
- `conflict_detected=true, conflict_note="候选上下文提及张小候已退场，但本章他再次出现，违和"`：疑似冲突（直觉违和）

**触发 S6 校验**：所有 `conflict_detected=true` 的记录将触发 S6 层的深度图遍历校验。

---

## 7. 完整示例

### 7.1 高价值记录（规则变动 + 角色弧光）

```json
{
  "event_id": "E_觉醒仪式",
  "stitch": {
    "sigma": "觉醒",
    "epsilon": "觉醒仪式",
    "kappa": "角色"
  },
  "coords": {
    "T": "E_module_博城篇",
    "L": "L_魔法学院",
    "C": "C_莫凡",
    "E": "",
    "R": "R_power"
  },
  "importance": "high",
  "delta_update": {
    "target_entity_id": "C_莫凡",
    "updated_fields": {
      "info": "莫凡在第4章觉醒仪式中觉醒雷系，成为罕见的双系法师。觉醒过程中雷印显现，引发全场震惊。此事件改变了莫凡的能力轨迹，使其从普通学徒跃升为双系法师。觉醒仪式由博城魔法学院主持，莫凡在众目睽睽之下完成觉醒，雷系能力的显现打破了单系觉醒的常规。此事件为莫凡角色弧光的关键转折点，时序归属博城篇模块。",
      "new_wiki_relations": [
        {"target": "L_博城", "type": "S_topo", "strength": "strong", "description": "地理归属"},
        {"target": "E_module_博城篇", "type": "T_branch", "strength": "strong", "description": "所属模块"},
        {"target": "I_雷印", "type": "R_strong", "strength": "strong", "description": "专属武器"},
        {"target": "C_莫凡_双系法师", "type": "A_arc", "strength": "strong", "description": "弧光转折"}
      ]
    },
    "conflict_detected": false,
    "conflict_note": ""
  }
}
```

### 7.2 中价值记录（关系发展，无规则变动）

```json
{
  "event_id": "E_同班相识",
  "stitch": {
    "sigma": "相识",
    "epsilon": "日常交往",
    "kappa": "角色"
  },
  "coords": {
    "T": "E_module_博城篇",
    "L": "L_魔法学院",
    "C": "C_莫凡",
    "E": "",
    "R": ""
  },
  "importance": "medium",
  "delta_update": {
    "target_entity_id": "C_莫凡",
    "updated_fields": {
      "info": "莫凡与张小候在魔法学院成为同班同学，建立友谊关系。张小候性格开朗，主动与莫凡结交，两人共同应对课业挑战。此关系为莫凡在学院建立的第一段同窗友谊，为后续共同成长奠定基础。此相识发生在博城篇模块的学院日常阶段，为莫凡社交网络的起点。",
      "new_wiki_relations": [
        {"target": "C_张小候", "type": "R_strong", "strength": "strong", "description": "同班挚友"}
      ]
    },
    "conflict_detected": false,
    "conflict_note": ""
  }
}
```

### 7.3 低价值记录（将被 low_value_filter 丢弃）

```json
{
  "event_id": "E_课间闲聊",
  "stitch": {
    "sigma": "闲聊",
    "epsilon": "日常对话",
    "kappa": "角色"
  },
  "coords": {
    "T": "E_module_博城篇",
    "L": "",
    "C": "C_莫凡",
    "E": "",
    "R": ""
  },
  "importance": "low",
  "delta_update": {
    "target_entity_id": "C_莫凡",
    "updated_fields": {
      "info": "莫凡与同学课间闲聊，讨论日常话题，无重要情节推进。",
      "new_wiki_relations": []
    },
    "conflict_detected": false,
    "conflict_note": ""
  }
}
```

**注**：此记录因 `importance=low` 且 `coords.R=""`（无规则变动），将被 `low_value_filter` 丢弃。
