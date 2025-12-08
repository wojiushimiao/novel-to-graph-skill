# Novel Analyzer Skill

三阶段小说精读分析工作流，用于生成深度文学批评报告。

## 结构

```
novel-analyzer/
├── SKILL.md              # 主技能文件（工作流编排指南）
└── prompts/              # 各阶段提示词模板
    ├── skim.md          # 阶段1: 粗读元数据提取
    ├── chunk.md         # 阶段2: 精读分块分析
    └── synthesize.md    # 阶段3: 整合生成报告
```

## 使用方式

技能会在用户请求分析小说时自动触发。

**触发示例**:
- "帮我分析这个小说 novel.txt"
- "深度解读 over_the_knee.txt"
- "生成 琼明神女录.txt 的文学分析报告"

## 输出示例

```
/tmp/novel_analysis/书名_20241208_162406/
├── metadata.json      # 元数据
├── chunks/            # 分块详细分析
│   ├── chunk_01.json
│   ├── chunk_02.json
│   └── ...
└── report.md          # 最终深度阅读报告（中文）
```

## 版本

- Version: 1.0
- Last updated: 2024-12-08
