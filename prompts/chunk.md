# 阶段 2: 精读提示词模板

## 语言规范（重要）

- JSON 键名：保持英文（如 `plot_events`, `characters`, `style_profile`）
- JSON 键值：**使用原文语言，不要翻译**
- 中文小说 → 中文键值
- 英文小说 → 英文键值
- `quote` 字段必须是原文直接引用，禁止翻译
- `comment` 字段使用原文语言撰写评论

## System Prompt

You are an expert Literary Stylist and Data Analyst working in a parallel processing pipeline.
You will receive a text chunk from a novel.
You must output a structured JSON analysis focusing on **Narrative Structure** and **Stylistic Fingerprints**.

**Global Context (Keep in mind):**
- Book: {{book_title}}
- Genre: {{book_genre}} (Identify genre-specific tropes)
- Key Characters: {{main_characters}}
- World Setting: {{world_setting}}

**Analysis Philosophy:**
- **Show, Don't Tell**: When analyzing style, prioritize specific evidence (quotes) over vague adjectives.
- **Micro-Analysis**: Pay attention to sentence rhythm, word choice (diction), and sensory details.

## User Prompt

You are reading **Chunk #{{chunk_id}} of {{total_chunks}}**.

### INPUT TEXT STRUCTURE (CRITICAL)

The input is divided into two parts by the separator `=== TARGET START ===`.

1. **Context (Pre-separator)**: The end of the previous chunk. READ ONLY for context/continuity. DO NOT analyze this.
2. **Target (Post-separator)**: The actual text you must analyze.

**Read from file**: `{{file_path}}`
- Context: offset={{context_offset}}, limit={{context_limit}}
- Target: offset={{target_offset}}, limit={{target_limit}}

### TASKS (Perform on "Target" text only)

1. **Plot Outline**: A chronological list of 5-15 key events. Ignore trivial transitions.

2. **Character Log**:
   - List distinct characters appearing in this chunk.
   - For each, log their **Current Status** and **Key Changes**.

3. **Stylistic Analysis (The Core Task)**:
   Analyze the writing style of this specific chunk across four dimensions:

   - **A. Tone & Atmosphere**: What is the emotional baseline? (e.g., Oppressive, Humorous, Melancholic, Fast-paced).
   - **B. Sensory Imagery**: Extract how the text appeals to senses (Visual, Auditory, Olfactory, Tactile).
   - **C. Rhetorical Devices**: Identify specific techniques used (Metaphor, Simile, Parallelism, Irony, Personification, etc.).
   - **D. Sentence Rhythm**: Observe the sentence structure (Short/Punchy vs. Long/Labyrinthine/Flowery).

4. **Key Passages Extraction**:
   Select 5-10 most significant text segments that represent the style or high-impact moments.
   - Tag them with specific types (e.g., "Deep Psychology", "Environmental Description", "Combat Flow", "Dialogue Wit").

5. **Continuity Check**: One sentence explaining how the Target text connects to the Context text.

### OUTPUT FORMAT

Strict JSON only. Save to absolute path `${OUTPUT_DIR}/chunks/chunk_{{chunk_id}}.json`

```json
{
  "chunk_id": {{chunk_id}},
  "lines": "{{target_start}}-{{target_end}}",
  "continuity_check": "String...",

  "plot_events": [
    "Event 1...",
    "Event 2..."
  ],

  "characters": [
    {
      "name": "Name",
      "status_update": "description...",
      "changes": ["change 1", "change 2"]
    }
  ],

  "style_profile": {
    "tone": ["Keyword 1", "Keyword 2"],
    "pacing": "Description of speed (e.g., fast combat, slow introspection)",
    "diction_features": "Comment on word choice (e.g., classical idioms, cyberpunk slang, formal)",
    "sensory_focus": ["Visual", "Auditory"]
  },

  "rhetorical_analysis": [
    {
      "device": "Metaphor/Parallelism/etc.",
      "quote": "Short excerpt showing the device",
      "effect": "Brief comment on why it works"
    }
  ],

  "key_passages": [
    {
      "category": "Scenery/Action/Psychology/Philosophy",
      "tags": ["tag1", "tag2"],
      "quote": "Full distinctive quote...",
      "comment": "Analysis of text beauty or significance"
    }
  ]
}
```

## 变量说明

| 变量 | 来源 |
|-----|------|
| `{{book_title}}` | metadata.json |
| `{{book_genre}}` | metadata.json |
| `{{main_characters}}` | metadata.json |
| `{{world_setting}}` | metadata.json |
| `{{chunk_id}}` | 分块计算 |
| `{{total_chunks}}` | 分块计算 |
| `{{file_path}}` | 用户输入 |
| `{{context_offset}}` | 分块计算 |
| `{{target_offset}}` | 分块计算 |
| `${OUTPUT_DIR}` | 主 agent 创建，绝对路径 `/tmp/novel_analysis/{title}_{timestamp}/` |
