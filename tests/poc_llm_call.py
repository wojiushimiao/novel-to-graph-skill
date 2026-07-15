#!/usr/bin/env python3
"""POC: 验证 LLM 调用流程可用"""
import sys
import os
import json
import time

sys.path.insert(0, r'd:\Gaia\06_核心代码')
os.environ['AUXILIARY_PROVIDER'] = 'deepseek'
os.environ['AUXILIARY_MODEL'] = 'deepseek-chat'

from shared.llm_infra.auxiliary_client import call_llm

msgs = [
    {'role': 'system', 'content': 'You output JSON only. No markdown, no explanation.'},
    {'role': 'user', 'content': 'Output a JSON object with key "test" and value "hello".'},
]

t0 = time.time()
try:
    r = call_llm(messages=msgs, task='poc_test', max_tokens=100, temperature=0.0)
    elapsed = time.time() - t0
    print(f'OK type: {type(r).__name__}')
    print(f'Elapsed: {elapsed:.2f}s')
    content = r.choices[0].message.content
    print(f'Content (first 300 chars): {content[:300]}')
    try:
        parsed = json.loads(content)
        print(f'Parsed JSON: {parsed}')
    except Exception as e:
        print(f'JSON parse failed: {e}')
except Exception as e:
    elapsed = time.time() - t0
    print(f'FAILED after {elapsed:.2f}s: {type(e).__name__}: {e}')
