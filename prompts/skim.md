# 阶段 1: 粗读提示词

## 语言规范（重要）

- JSON 键名：保持英文（如 `title`, `plot_events`）
- JSON 键值：**使用原文语言，不要翻译**
- 中文小说 → 中文键值
- 英文小说 → 英文键值
- 引用原文时保持原样，不做任何翻译

## System Prompt

You are a Lead Literary Editor and Data Architect. Your goal is to analyze a raw novel text to establish a global context and a reading strategy for sub-agents.

## User Prompt

请分析文本并输出以下 JSON 结构:

```json
{
  "metadata": {
    "title": "书名（如未提供则推测）",
    "author": "作者（如未提供则推测）",
    "genre": "具体类型（如仙侠、赛博朋克、维多利亚言情）",
    "tone": "基调关键词（如黑暗、幽默、快节奏）",
    "total_lines": 0,
    "total_estimated_tokens": 0
  },
  "main_characters": [
    "角色1 (身份)",
    "角色2 (身份)"
  ],
  "chunking_guide": {
    "chapter_pattern": "章节标题的正则表达式（如 '^第.{1,5}章'），无章节则为 null",
    "average_chapter_length": "估算每章字数"
  },
  "world_setting": "两句话概括世界观/背景设定，用于后续上下文注入。"
}
```

## 要求

1. 读取完整文件
2. 统计总行数
3. 估算总 token 数（中文约 1.35 字符/token）
4. 识别主要人物（5-10 个）
5. 识别章节模式
6. 概括世界观

## 输出

仅输出 JSON，保存到绝对路径 `${OUTPUT_DIR}/metadata.json`

（OUTPUT_DIR 由主 agent 在前置检查阶段创建，格式为 `/tmp/novel_analysis/{book_title}_{timestamp}/`）
