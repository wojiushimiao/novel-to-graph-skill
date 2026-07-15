#!/usr/bin/env python3
"""测试 LLM 调用和 chunk 数量"""
import sys
import os
import time

SKILL_DIR = os.path.normpath(r'D:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
CORE_DIR = os.path.normpath(r'D:\Gaia\06_核心代码')
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, CORE_DIR)

os.environ.setdefault('AUXILIARY_PROVIDER', 'deepseek')
os.environ.setdefault('AUXILIARY_MODEL', 'deepseek-chat')

from tools.text_chunker import read_file, chunk_text
from shared.llm_infra.auxiliary_client import call_llm

# 检查 chunk 数量
novel_path = os.path.normpath(r'D:\Gaia\07_子项目代码\LLM对话作品卡\全职法师\novel_text\full_novel.txt')
text = read_file(novel_path)
print(f'文本长度: {len(text)} chars')
chunks = chunk_text(text, source='full_novel')
print(f'总 chunk 数: {len(chunks)}')
print(f'首个 chunk: index={chunks[0].index}, chapter={chunks[0].chapter}, chars={len(chunks[0].content)}')

# 测试一次 LLM 调用（仅第1个 chunk 的前3000字）
prompt_path = os.path.join(SKILL_DIR, 'prompts', 'extraction_meta_prompt.md')
system_prompt = open(prompt_path, 'r', encoding='utf-8').read()
print(f'system_prompt 长度: {len(system_prompt)} chars')

t0 = time.time()
response = call_llm(
    messages=[
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': f'请对以下小说文本执行语义抽取。\n\n章节: {chunks[0].chapter}\n文本:\n{chunks[0].content[:3000]}...\n\n（由于测试目的仅截取前3000字）'}
    ],
    task='novel_extraction_test',
    max_tokens=2048,
    temperature=0.1,
    timeout=60.0,
)
elapsed = time.time() - t0
content = response.choices[0].message.content
print(f'LLM 调用成功! 耗时: {elapsed:.1f}s')
print(f'响应长度: {len(content)} chars')
print(f'响应前200字: {content[:200]}')