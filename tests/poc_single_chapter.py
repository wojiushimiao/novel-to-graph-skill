#!/usr/bin/env python3
"""POC: 单章 LLM 抽取验证

测试用 extraction_meta_prompt.md 作为 system prompt，对小说第1章执行语义抽取。
验证输出 JSON 是否符合 schema_specification.md。
评估单章抽取耗时。
"""
import sys
import os
import json
import time
from pathlib import Path

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
NOVEL_PATH = Path(r'D:\Gaia\07_子项目代码\LLM对话作品卡\全职法师\novel_text\full_novel.txt')

sys.path.insert(0, r'd:\Gaia\06_核心代码')
sys.path.insert(0, str(SKILL_DIR))

os.environ['AUXILIARY_PROVIDER'] = 'deepseek'
os.environ['AUXILIARY_MODEL'] = 'deepseek-chat'

from tools.text_chunker import chunk_text, read_file
from shared.llm_infra.auxiliary_client import call_llm


def load_system_prompt() -> str:
    """读取 extraction_meta_prompt.md 作为 system prompt"""
    prompt_path = SKILL_DIR / 'prompts' / 'extraction_meta_prompt.md'
    return prompt_path.read_text(encoding='utf-8')


def get_first_chapter():
    """读取小说并取第1个 chunk"""
    print(f'[1] 读取小说: {NOVEL_PATH}')
    text = read_file(NOVEL_PATH)
    print(f'    文本长度: {len(text)} chars')

    print('[2] 分块...')
    chunks = chunk_text(text, source='full_novel')
    print(f'    总块数: {len(chunks)}')

    first = chunks[0]
    print(f'[3] 第1个 chunk: index={first.index}, chapter={first.chapter!r}, char_count={first.char_count}')
    print(f'    内容前200字: {first.content[:200]!r}')
    return first, chunks


def call_llm_for_chunk(chunk, system_prompt: str):
    """对单个 chunk 调用 LLM 抽取"""
    user_msg = f"""请对以下小说文本执行语义抽取，按 Schema 规范输出 JSON 对象列表（3-8 条）。

章节: {chunk.chapter}
文本:
{chunk.content}
"""
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_msg},
    ]
    return call_llm(
        messages=messages,
        task='novel_extraction',
        max_tokens=4096,
        temperature=0.1,
    )


def validate_output(content: str) -> dict:
    """验证 LLM 输出"""
    # 尝试去除 markdown 标记
    cleaned = content.strip()
    if cleaned.startswith('```'):
        # 去除 ```json 或 ``` 标记
        lines = cleaned.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        cleaned = '\n'.join(lines)

    try:
        data = json.loads(cleaned)
        return {'valid': True, 'data': data, 'cleaned': cleaned}
    except json.JSONDecodeError as e:
        return {'valid': False, 'error': str(e), 'cleaned': cleaned}


def main():
    print('=== POC: 单章 LLM 抽取验证 ===\n')

    system_prompt = load_system_prompt()
    print(f'[1] system_prompt 长度: {len(system_prompt)} chars\n')

    chunk, all_chunks = get_first_chapter()
    print()

    print(f'[4] 调用 LLM 抽取 (DeepSeek)...')
    t0 = time.time()
    try:
        response = call_llm_for_chunk(chunk, system_prompt)
        elapsed = time.time() - t0
        print(f'    耗时: {elapsed:.2f}s')
        content = response.choices[0].message.content
        print(f'    输出长度: {len(content)} chars')
        print(f'    输出前500字: {content[:500]!r}')
        print()

        print('[5] 验证 JSON 格式...')
        result = validate_output(content)
        if result['valid']:
            data = result['data']
            if isinstance(data, list):
                print(f'    ✅ JSON 解析成功 (list, {len(data)} 条)')
                for i, item in enumerate(data):
                    print(f'    [{i}] event_id={item.get("event_id")}, importance={item.get("importance")}, target={item.get("delta_update",{}).get("target_entity_id")}')
                    info = item.get('delta_update', {}).get('updated_fields', {}).get('info', '')
                    print(f'        info 长度: {len(info)} 字')
            elif isinstance(data, dict):
                print(f'    ✅ JSON 解析成功 (dict)')
                print(f'    event_id={data.get("event_id")}, importance={data.get("importance")}')
                info = data.get('delta_update', {}).get('updated_fields', {}).get('info', '')
                print(f'    info 长度: {len(info)} 字')
            print()

            print('[6] 估算全量耗时...')
            avg_time = elapsed
            total_chunks = len(all_chunks)
            serial_total = avg_time * total_chunks
            print(f'    单章耗时: {avg_time:.2f}s')
            print(f'    总块数: {total_chunks}')
            print(f'    串行总耗时: {serial_total:.0f}s = {serial_total/60:.1f}min = {serial_total/3600:.2f}h')
            print(f'    并发=4: {serial_total/4:.0f}s = {serial_total/4/60:.1f}min')
            print(f'    并发=8: {serial_total/8:.0f}s = {serial_total/8/60:.1f}min')
        else:
            print(f'    ❌ JSON 解析失败: {result["error"]}')
            print(f'    cleaned 前500字: {result["cleaned"][:500]!r}')

    except Exception as e:
        elapsed = time.time() - t0
        print(f'    FAILED after {elapsed:.2f}s: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
