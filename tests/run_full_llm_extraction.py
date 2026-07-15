#!/usr/bin/env python3
"""novel-analysis-skill · 全量 LLM 抽取脚本 (S3 阶段)

按 extraction_meta_prompt.md 规则，对 full_novel.txt 的每个 chunk 调用 LLM 执行语义抽取。

特性:
- 断点续抽: 已完成的 chunk 跳过（基于 llm_outputs/ 目录中的文件）
- 并发控制: ThreadPoolExecutor 并发调用 LLM
- 错误重试: 失败自动重试 3 次
- 进度显示: 实时显示进度、ETA、成功率
- 增量保存: 每个 chunk 抽取完成后立即保存到 llm_outputs/ 目录

输出:
- llm_outputs/chunk_{idx:05d}.json — 单 chunk 抽取结果
- llm_outputs_full_llm.json — 合并后的完整 LLM 输出
- extraction_progress.json — 抽取进度
"""
from __future__ import annotations

import sys
import os
import json
import time
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

SKILL_DIR = Path(r'd:\Gaia\08_记忆数据\knowledge-base\skills\novel-analysis-skill')
NOVEL_PATH = Path(r'D:\Gaia\07_子项目代码\LLM对话作品卡\全职法师\novel_text\full_novel.txt')
WORKSPACE = SKILL_DIR / 'tests' / 'extraction_workspace_llm'
LLM_OUTPUTS_DIR = WORKSPACE / 'llm_outputs'
CHUNKS_CACHE = WORKSPACE / 'chunks' / 'chunks.json'
PROGRESS_FILE = WORKSPACE / 'extraction_progress.json'
FINAL_OUTPUT = WORKSPACE / 'llm_outputs_full_llm.json'
DISTILL_DIR = WORKSPACE / 'distill'  # v0.4.1: Document Distiller 缓存目录

sys.path.insert(0, r'd:\Gaia\06_核心代码')
sys.path.insert(0, str(SKILL_DIR))

os.environ.setdefault('AUXILIARY_PROVIDER', 'deepseek')
os.environ.setdefault('AUXILIARY_MODEL', 'deepseek-chat')

from tools.text_chunker import chunk_text, read_file
from tools.models import Chunk
from tools.document_distiller import distill_chunk  # v0.4.1: Document Distiller
from shared.llm_infra.auxiliary_client import call_llm

# ─── 配置 ──────────────────────────────────────────────────
CONCURRENCY = int(os.getenv("NAS_CONCURRENCY", "6"))  # 并发数（可由 NAS_CONCURRENCY 覆盖）
MAX_RETRIES = 3           # 最大重试次数
RETRY_DELAY = 5.0         # 重试延迟(秒)
LLM_TIMEOUT = 120.0       # LLM 调用超时(秒)
MAX_TOKENS = 8192         # LLM 最大输出 tokens
TEMPERATURE = 0.1         # 温度参数
SAVE_EVERY = 20           # 每 N 个 chunk 保存一次合并文件

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('llm_extract')

# ─── 全局状态 ──────────────────────────────────────────────
_lock = threading.Lock()
_completed = 0
_failed = 0
_started_at = 0.0


def load_system_prompt() -> str:
    """读取 extraction_meta_prompt.md 作为 system prompt"""
    prompt_path = SKILL_DIR / 'prompts' / 'extraction_meta_prompt.md'
    return prompt_path.read_text(encoding='utf-8')


def get_chunks() -> list[dict]:
    """获取所有 chunks（带缓存）"""
    if CHUNKS_CACHE.exists():
        logger.info(f'从缓存加载 chunks: {CHUNKS_CACHE}')
        data = json.loads(CHUNKS_CACHE.read_text(encoding='utf-8'))
        logger.info(f'缓存 chunk 数: {len(data)}')
        return data

    # 确保目录存在
    CHUNKS_CACHE.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f'读取小说: {NOVEL_PATH}')
    text = read_file(NOVEL_PATH)
    logger.info(f'文本长度: {len(text)} chars')

    logger.info('分块中...')
    chunks = chunk_text(text, source='full_novel')
    logger.info(f'总块数: {len(chunks)}')

    data = [
        {
            'index': c.index,
            'chapter': c.chapter,
            'content': c.content,
            'char_offset': c.char_offset,
            'char_count': c.char_count,
            'chunk_id': c.chunk_id,
        }
        for c in chunks
    ]
    CHUNKS_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    logger.info(f'chunks 缓存已保存: {CHUNKS_CACHE} ({CHUNKS_CACHE.stat().st_size/1024/1024:.1f}MB)')
    return data


def is_chunk_done(idx: int) -> bool:
    """检查 chunk 是否已完成"""
    out_file = LLM_OUTPUTS_DIR / f'chunk_{idx:05d}.json'
    return out_file.exists()


def build_user_message(chunk: dict, distill_context: dict | None = None) -> str:
    """构造 user message，强化 info 字数要求。

    v0.4.1 升级: 接受可选的 distill_context，将 Document Distiller 输出
    的 Blueprint 上下文注入到 S3 prompt 中，辅助 LLM 抽取。

    Args:
        chunk: 原始 chunk 字典
        distill_context: Document Distiller 输出（可选）。
            含字段: scene/action/change/causality/raw_summary/skipped
            当 skipped=True 时，raw_summary 即为原始 chunk 文本。
    """
    # 构造 distill 上下文块（若有）
    distill_block = ''
    if distill_context is not None:
        blueprint_summary = distill_context.get('raw_summary', '')
        if blueprint_summary:
            distill_block = f"""
【Document Distiller Blueprint 上下文（v0.4.1 预处理）】
以下是文本蒸馏器的结构化提炼，作为辅助上下文使用：
{blueprint_summary}

注: 此 Blueprint 仅供参考，info 字段仍需基于原文 [src:chunk_NNN] 重新提炼。
"""
        else:
            distill_block = ''

    return f"""请对以下小说文本执行语义抽取。

【强制要求】
1. 输出必须是 JSON 数组（3-8 个对象），不要输出 Markdown 代码块标记
2. 每个 info 字段必须 500-1500 字，必须是语义提炼摘要（非原文摘录拼凑）
3. event_id 必须基于核心客观事实名词（禁用主观修饰词）
4. 关联事件必须聚合为统一条目（起因/经过/结果/各方反应/原子化动作序列）
5. 单个对话/动作/描写不得作为独立事件单元
6. 强连续序列用索引跳转（info 中记录"前序事件: E_xxx"），不建关系边
7. 疑似冲突即上报 conflict_detected=true（不要求举证）
{distill_block}
章节: {chunk['chapter']}
文本:
{chunk['content']}
"""


def distill_chunk_cached(
    chunk: dict,
    llm_client=None,
) -> dict:
    """对单个 chunk 执行 Document Distiller 预处理（带缓存）。

    v0.4.1 新增: S2.8 预处理阶段。对每个 chunk 调用 document_distiller.distill_chunk，
    产出 Blueprint 上下文供 S3 抽取使用。结果缓存到 DISTILL_DIR 下，可复用。

    降级开关:
        环境变量 NOVEL_ANALYSIS_SKIP_DISTILL=1 时跳过 distill，返回 skipped=True
        的占位结果，raw_summary 即为原始 chunk 文本。

    Args:
        chunk: chunk 字典，含 index/content 等字段
        llm_client: LLM 调用函数（Callable[[str], str]）。
            若为 None，则使用 call_llm 适配器（实际 LLM 调用）。

    Returns:
        Document Distiller 输出 dict，含字段:
        - scene/action/change/causality: Blueprint 四字段
        - raw_summary: 拼接的摘要文本（skipped 时为原始 chunk）
        - skipped: 是否被降级跳过
        - chunk_index: chunk 索引
    """
    chunk_index = chunk.get('index', 0)
    chunk_text_content = chunk.get('content', '')

    # 确保缓存目录存在
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = DISTILL_DIR / f'distill_{chunk_index:05d}.json'

    # Step 1: 检查缓存
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding='utf-8'))
            logger.debug(f'Distiller 缓存命中 (chunk_index={chunk_index})')
            return cached
        except Exception as exc:
            logger.warning(f'Distiller 缓存读取失败，重新生成 (chunk_index={chunk_index}): {exc}')

    # Step 2: 调用 document_distiller.distill_chunk
    # 若未提供 llm_client，使用 call_llm 适配器
    if llm_client is None:
        llm_client = _build_distill_llm_client()

    result = distill_chunk(
        chunk_text=chunk_text_content,
        llm_client=llm_client,
        chunk_index=chunk_index,
    )

    # Step 3: 保存到缓存（即使 skipped 也保存，避免重复判断环境变量）
    try:
        cache_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    except Exception as exc:
        logger.warning(f'Distiller 缓存写入失败 (chunk_index={chunk_index}): {exc}')

    return result


def _build_distill_llm_client():
    """构造 Distiller 使用的 LLM 客户端适配器。

    将 call_llm（来自 shared.llm_infra.auxiliary_client）适配为
    distill_chunk 所需的 Callable[[str], str] 接口。
    """
    def _client(prompt: str) -> str:
        messages = [
            {'role': 'system', 'content': '你是严格的文本蒸馏器。'},
            {'role': 'user', 'content': prompt},
        ]
        response = call_llm(
            messages=messages,
            task='novel_distill',
            max_tokens=1024,
            temperature=0.1,
            timeout=60.0,
        )
        return response.choices[0].message.content

    return _client


def extract_chunk(chunk: dict, system_prompt: str) -> dict:
    """对单个 chunk 执行 LLM 抽取（带重试）"""
    idx = chunk['index']

    # v0.4.1: S2.8 Document Distiller 预处理（带缓存）
    # 失败不阻断主流程，distill_context 为 None 时退回无上下文模式
    distill_context: dict | None = None
    try:
        distill_context = distill_chunk_cached(chunk)
    except Exception as exc:
        logger.warning(f'chunk {idx} Distiller 预处理失败，退回无上下文模式: {exc}')

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': build_user_message(chunk, distill_context=distill_context)},
    ]

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            t0 = time.time()
            response = call_llm(
                messages=messages,
                task='novel_extraction',
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                timeout=LLM_TIMEOUT,
            )
            elapsed = time.time() - t0
            content = response.choices[0].message.content

            # 清理 markdown 标记
            cleaned = content.strip()
            if cleaned.startswith('```'):
                lines = cleaned.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].startswith('```'):
                    lines = lines[:-1]
                cleaned = '\n'.join(lines)

            # 尝试解析 JSON
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # 尝试提取数组部分
                import re
                arr_match = re.search(r'\[\s*\{.*\}\s*\]', cleaned, re.DOTALL)
                if arr_match:
                    data = json.loads(arr_match.group(0))
                else:
                    raise

            # 规范化为列表
            if isinstance(data, dict):
                data = [data]
            elif not isinstance(data, list):
                raise ValueError(f'LLM 输出不是 JSON 数组或对象: {type(data)}')

            return {
                'chunk_index': idx,
                'chapter': chunk['chapter'],
                'chunk_id': chunk['chunk_id'],
                'elapsed': elapsed,
                'items': data,
                'attempt': attempt,
            }

        except Exception as e:
            last_err = e
            logger.warning(f'chunk {idx} attempt {attempt}/{MAX_RETRIES} 失败: {type(e).__name__}: {str(e)[:100]}')
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f'chunk {idx} 抽取失败（{MAX_RETRIES}次重试后）: {last_err}')


def save_chunk_result(result: dict) -> None:
    """保存单 chunk 结果到文件"""
    idx = result['chunk_index']
    out_file = LLM_OUTPUTS_DIR / f'chunk_{idx:05d}.json'
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


def update_progress(total: int) -> None:
    """更新进度文件"""
    global _completed, _failed
    elapsed = time.time() - _started_at
    progress = {
        'total': total,
        'completed': _completed,
        'failed': _failed,
        'elapsed_seconds': elapsed,
        'eta_seconds': (elapsed / max(_completed, 1)) * (total - _completed - _failed) if _completed > 0 else None,
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')


def merge_all_results(total: int) -> list[dict]:
    """合并所有 chunk 结果"""
    all_items = []
    for idx in range(total):
        out_file = LLM_OUTPUTS_DIR / f'chunk_{idx:05d}.json'
        if not out_file.exists():
            continue
        try:
            result = json.loads(out_file.read_text(encoding='utf-8'))
            for item in result.get('items', []):
                item['_source_chunk'] = idx
                item['_source_chapter'] = result.get('chapter', '')
                all_items.append(item)
        except Exception as e:
            logger.warning(f'合并 chunk {idx} 失败: {e}')
    return all_items


def main():
    global _completed, _failed, _started_at

    print('=== novel-analysis-skill · 全量 LLM 抽取 (S3) ===\n')

    # 确保工作目录存在
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    LLM_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)  # v0.4.1: Distiller 缓存目录

    # 加载 system prompt
    system_prompt = load_system_prompt()
    print(f'[1] system_prompt 长度: {len(system_prompt)} chars')

    # 获取 chunks
    chunks = get_chunks()
    total = len(chunks)
    print(f'[2] 总 chunk 数: {total}')

    # 检查已完成
    done_count = sum(1 for i in range(total) if is_chunk_done(i))
    print(f'[3] 已完成: {done_count}/{total} ({done_count*100/total:.1f}%)')
    pending = [c for c in chunks if not is_chunk_done(c['index'])]
    print(f'[4] 待抽取: {len(pending)}')

    if not pending:
        print('    所有 chunk 已完成，跳过抽取阶段')
    else:
        print(f'[5] 开始抽取 (并发={CONCURRENCY}, 预计耗时 {len(pending)*18/CONCURRENCY/60:.1f}min)')
        _started_at = time.time()

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = {
                executor.submit(extract_chunk, chunk, system_prompt): chunk
                for chunk in pending
            }

            for future in as_completed(futures):
                chunk = futures[future]
                idx = chunk['index']
                try:
                    result = future.result()
                    save_chunk_result(result)
                    with _lock:
                        _completed += 1
                        done = _completed
                        fail = _failed
                    if done % 10 == 0 or done <= 5:
                        elapsed = time.time() - _started_at
                        eta = (elapsed / done) * (len(pending) - done - fail) if done > 0 else 0
                        logger.info(
                            f'进度 {done}/{len(pending)} '
                            f'({done*100/len(pending):.1f}%) '
                            f'chunk={idx} '
                            f'items={len(result["items"])} '
                            f'elapsed={elapsed:.0f}s '
                            f'ETA={eta:.0f}s ({eta/60:.1f}min)'
                        )
                    if done % SAVE_EVERY == 0:
                        update_progress(total)
                except Exception as e:
                    with _lock:
                        _failed += 1
                        fail = _failed
                        done = _completed
                    logger.error(f'chunk {idx} 最终失败: {e}')
                    # 保存错误信息
                    err_file = LLM_OUTPUTS_DIR / f'chunk_{idx:05d}_error.json'
                    err_file.write_text(json.dumps({
                        'chunk_index': idx,
                        'chapter': chunk['chapter'],
                        'error': str(e),
                        'error_type': type(e).__name__,
                    }, ensure_ascii=False, indent=2), encoding='utf-8')

        update_progress(total)
        elapsed = time.time() - _started_at
        print(f'\n[6] 抽取完成: 成功={_completed}, 失败={_failed}, 耗时={elapsed:.0f}s ({elapsed/60:.1f}min)')

    # 合并所有结果
    print(f'\n[7] 合并所有 chunk 结果到 {FINAL_OUTPUT}')
    all_items = merge_all_results(total)
    FINAL_OUTPUT.write_text(json.dumps(all_items, ensure_ascii=False), encoding='utf-8')
    print(f'    合并完成: {len(all_items)} 条记录')
    print(f'    文件大小: {FINAL_OUTPUT.stat().st_size/1024/1024:.1f}MB')

    # 统计
    print(f'\n[8] 统计信息:')
    importance_dist = {'high': 0, 'medium': 0, 'low': 0}
    info_lengths = []
    conflict_count = 0
    for item in all_items:
        imp = item.get('importance', 'low')
        if imp in importance_dist:
            importance_dist[imp] += 1
        info = item.get('delta_update', {}).get('updated_fields', {}).get('info', '')
        info_lengths.append(len(info))
        if item.get('delta_update', {}).get('conflict_detected', False):
            conflict_count += 1

    print(f'    总记录数: {len(all_items)}')
    print(f'    importance 分布: {importance_dist}')
    if info_lengths:
        print(f'    info 长度: min={min(info_lengths)}, max={max(info_lengths)}, avg={sum(info_lengths)/len(info_lengths):.1f}')
        qualified = sum(1 for l in info_lengths if 500 <= l <= 1500)
        print(f'    info 达标率 (500-1500字): {qualified}/{len(info_lengths)} ({qualified*100/len(info_lengths):.1f}%)')
    print(f'    冲突检测数: {conflict_count}')


if __name__ == '__main__':
    main()
