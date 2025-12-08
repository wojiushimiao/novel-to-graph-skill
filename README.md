# Novel Analyzer Skill

四阶段小说深度分析工作流，支持并行精读、文学批评报告生成和角色档案提取。

## 工作流程

```
阶段1: 粗读元数据提取 (主agent执行)
  ↓ 生成 metadata.json

阶段2: 并行精读分块 (多个general-purpose agents)
  ↓ 生成 chunk_01.json ~ chunk_N.json

阶段3: 整合生成报告 (1个general-purpose agent)
  ↓ 生成 report.md

阶段4: 角色档案生成 (可选, 1个general-purpose agent)
  ↓ 生成 characters/profile_<角色名>.md
```

## 目录结构

```
novel-analyzer/
├── SKILL.md                        # 主技能文件（工作流编排指南）
└── prompts/                        # 各阶段提示词模板
    ├── skim.md                     # 阶段1: 粗读元数据提取
    ├── chunk.md                    # 阶段2: 精读分块分析
    ├── synthesize.md               # 阶段3: 整合生成报告
    └── character-profile.md        # 阶段4: 角色档案生成
```

## 核心特性

- **并行加速**: 自动分块并启动多个agents并行精读（最多16个）
- **角色追踪模式**: 在精读阶段提前收集特定角色的所有信息
- **中文报告**: 全中文输出，原文引用保留不翻译
- **文学批评级别**: 含情节、人物弧光、文体分析、修辞手法、黄金语录

## 使用方式

### 基础分析
```
"帮我深度分析 novel.txt"
"精读 琼明神女录.txt"
```

### 分析 + 角色档案
```
"分析 novel.txt，并生成季婵溪的角色档案"
"精读小说，生成主角档案"
```

### 仅生成角色档案（需已有分析数据）
```
"生成裴语涵的角色档案"
```

## 输出示例

```
/tmp/novel_analysis/<书名>_<timestamp>/
├── metadata.json              # 全书元数据
├── chunks/                    # 分块详细分析 (N个JSON)
│   ├── chunk_01.json
│   ├── chunk_02.json
│   └── ...
├── report.md                  # 📖 深度阅读报告（中文）
└── characters/                # 📋 角色档案（如有）
    └── profile_<角色名>.md
```

## 实际案例

**小说**: 《琼明神女录》（42,380行，106万字）
**执行时间**: 约15分钟（16个opus agents并行）
**输出**:
- 深度报告：802行，涵盖情节、人物、文风、主题
- 季婵溪角色档案：401行，包含完整履历、台词、心理分析

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `target_tokens_per_chunk` | 50000 | 每块目标token数 |
| `overlap_lines` | 200 | 块间重叠行数 |
| `chars_per_token` | 1.35 | 中文字符/token比率 |
| `max_concurrent_agents` | 16 | 最大并行agent数 |

## 版本

- Version: 1.1
- Last updated: 2025-12-08
