#!/usr/bin/env python3
"""测试全量导入 - 修复导入顺序"""
import sys
import os

SKILL_DIR = os.path.normpath(r'D:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
CORE_DIR = os.path.normpath(r'D:\Gaia\06_核心代码')

# 关键：CORE_DIR 先插入（位置1），SKILL_DIR 后插入（位置0，优先）
sys.path.insert(0, CORE_DIR)
sys.path.insert(0, SKILL_DIR)

print(f'sys.path[0]={sys.path[0]}')
print(f'sys.path[1]={sys.path[1]}')

# Test import chain
print('\n--- Testing imports ---')
try:
    from tools.text_chunker import read_file, chunk_text
    print('OK: tools.text_chunker')
except Exception as e:
    print(f'FAIL: tools.text_chunker: {e}')

try:
    from shared.llm_infra.auxiliary_client import call_llm
    print('OK: shared.llm_infra.auxiliary_client')
except Exception as e:
    print(f'FAIL: shared.llm_infra.auxiliary_client: {e}')

try:
    from tools import schema_validator
    print('OK: tools.schema_validator')
except Exception as e:
    print(f'FAIL: tools.schema_validator: {e}')

# Test actual task
print('\n--- Testing chunking ---')
try:
    novel_path = os.path.normpath(r'D:\Gaia\07_子项目代码\LLM对话作品卡\全职法师\novel_text\full_novel.txt')
    text = read_file(novel_path)
    print(f'OK: text length = {len(text)} chars')
    chunks = chunk_text(text, source='full_novel')
    print(f'OK: {len(chunks)} chunks')
    if chunks:
        print(f'First chunk: index={chunks[0].index}, chapter={chunks[0].chapter}, chars={len(chunks[0].content)}')
except Exception as e:
    print(f'FAIL: chunking: {type(e).__name__}: {e}')