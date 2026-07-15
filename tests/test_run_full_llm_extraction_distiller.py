#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-analysis-skill · T-D2 run_full_llm_extraction.py Distiller 集成测试

锚定: v0.4.1_plan_final.md §T-D2
检查点: CP-D2.1 (distill 注入 S3 prompt) + CP-D2.2 (缓存可复用) + CP-D2.3 (降级开关生效)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将 tests 目录加入路径以导入 run_full_llm_extraction
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# 将 tools 目录加入路径
_TOOLS_DIR = _TESTS_DIR.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# 导入待测模块
import run_full_llm_extraction as rfe  # noqa: E402


# ─── CP-D2.1: distill 输出正确注入到 S3 prompt ──────────────────

class TestDistillInjectionToPrompt:
    """验证 distill 输出被正确注入到 S3 的 LLM prompt。"""

    def test_build_user_message_accepts_distill_context(self):
        """build_user_message 应接受 distill_context 参数。"""
        chunk = {
            'index': 0,
            'chapter': '第一章',
            'content': '原始 chunk 文本',
        }
        distill_context = {
            'scene': '场景描述',
            'action': '行动描述',
            'change': '变动描述',
            'causality': '因果描述',
            'raw_summary': '场景：场景描述\n行动：行动描述\n变动：变动描述\n因果：因果描述',
            'skipped': False,
            'chunk_index': 0,
        }
        # 不应抛出异常
        message = rfe.build_user_message(chunk, distill_context=distill_context)
        assert isinstance(message, str)
        assert len(message) > 0

    def test_build_user_message_includes_distill_blueprint(self):
        """build_user_message 应包含 distill 的 Blueprint 字段。"""
        chunk = {
            'index': 1,
            'chapter': '第二章',
            'content': '原文 chunk 内容',
        }
        distill_context = {
            'scene': '魔法学院',
            'action': '莫凡施法',
            'change': '规则变动X',
            'causality': '前因 → 后果',
            'raw_summary': '场景：魔法学院\n行动：莫凡施法\n变动：规则变动X\n因果：前因 → 后果',
            'skipped': False,
            'chunk_index': 1,
        }
        message = rfe.build_user_message(chunk, distill_context=distill_context)
        # 应包含 Blueprint 字段
        assert '魔法学院' in message
        assert '莫凡施法' in message
        assert '规则变动X' in message

    def test_build_user_message_without_distill_backward_compatible(self):
        """无 distill_context 时应向后兼容（使用原始 chunk）。"""
        chunk = {
            'index': 0,
            'chapter': '第一章',
            'content': '原始 chunk 文本内容',
        }
        # 不传 distill_context，应不抛异常
        message = rfe.build_user_message(chunk)
        assert '原始 chunk 文本内容' in message


# ─── CP-D2.2: distill 缓存文件存在且可读取 ──────────────────────

class TestDistillCache:
    """验证 distill 结果缓存机制。"""

    def test_distill_dir_constant_exists(self):
        """DISTILL_DIR 路径常量应存在。"""
        assert hasattr(rfe, 'DISTILL_DIR')
        assert isinstance(rfe.DISTILL_DIR, Path)

    def test_distill_chunk_cached_function_exists(self):
        """distill_chunk_cached 函数应存在。"""
        assert hasattr(rfe, 'distill_chunk_cached')
        assert callable(rfe.distill_chunk_cached)

    def test_distill_cache_reuse_existing(self, tmp_path, monkeypatch):
        """缓存存在时应直接读取，不调用 LLM。"""
        # 准备：构造一个 chunk 和对应的缓存文件
        chunk = {
            'index': 5,
            'chapter': '第五章',
            'content': '原文内容',
        }
        cache_data = {
            'scene': '缓存场景',
            'action': '缓存行动',
            'change': '缓存变动',
            'causality': '缓存因果',
            'raw_summary': '场景：缓存场景\n行动：缓存行动',
            'skipped': False,
            'chunk_index': 5,
        }
        # 修改 DISTILL_DIR 到临时目录
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / 'distill_00005.json'
        cache_file.write_text(json.dumps(cache_data, ensure_ascii=False), encoding='utf-8')

        # 调用 distill_chunk_cached，不应调用 LLM
        llm_mock = MagicMock(return_value='should not be called')
        result = rfe.distill_chunk_cached(chunk, llm_client=llm_mock)

        assert result['scene'] == '缓存场景'
        assert result['chunk_index'] == 5
        llm_mock.assert_not_called()

    def test_distill_cache_save_new_result(self, tmp_path, monkeypatch):
        """新 distill 结果应保存到缓存文件。"""
        chunk = {
            'index': 7,
            'chapter': '第七章',
            'content': '原文 chunk 内容',
        }
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)

        # mock llm_client 返回 Blueprint 文本
        def mock_llm(prompt: str) -> str:
            return (
                '场景：测试场景\n'
                '行动：测试行动\n'
                '变动：测试变动\n'
                '因果：测试因果'
            )

        result = rfe.distill_chunk_cached(chunk, llm_client=mock_llm)

        # 缓存文件应存在
        cache_file = tmp_path / 'distill_00007.json'
        assert cache_file.exists()
        saved = json.loads(cache_file.read_text(encoding='utf-8'))
        assert saved['scene'] == '测试场景'
        assert saved['chunk_index'] == 7
        assert result['scene'] == '测试场景'


# ─── CP-D2.3: 降级开关生效 ─────────────────────────────────────

class TestDistillDegradation:
    """验证 NOVEL_ANALYSIS_SKIP_DISTILL 降级开关。"""

    def test_skip_distill_env_var_returns_raw_chunk(self, tmp_path, monkeypatch):
        """NOVEL_ANALYSIS_SKIP_DISTILL=1 时应返回 skipped=True 的原始 chunk。"""
        chunk = {
            'index': 10,
            'chapter': '第十章',
            'content': '原始 chunk 文本',
        }
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.setenv('NOVEL_ANALYSIS_SKIP_DISTILL', '1')

        llm_mock = MagicMock(return_value='should not be called')
        result = rfe.distill_chunk_cached(chunk, llm_client=llm_mock)

        assert result['skipped'] is True
        assert result['raw_summary'] == '原始 chunk 文本'
        llm_mock.assert_not_called()

    def test_skip_distill_zero_executes_distill(self, tmp_path, monkeypatch):
        """NOVEL_ANALYSIS_SKIP_DISTILL=0 或未设置时应正常调用 distill。"""
        chunk = {
            'index': 11,
            'chapter': '第十一章',
            'content': '原始 chunk 文本',
        }
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.setenv('NOVEL_ANALYSIS_SKIP_DISTILL', '0')

        def mock_llm(prompt: str) -> str:
            return '场景：A\n行动：B\n变动：C\n因果：D'

        result = rfe.distill_chunk_cached(chunk, llm_client=mock_llm)

        assert result['skipped'] is False
        assert result['scene'] == 'A'
        assert result['action'] == 'B'

    def test_skip_distill_unsets_env_uses_distill(self, tmp_path, monkeypatch):
        """未设置 NOVEL_ANALYSIS_SKIP_DISTILL 时应正常调用 distill。"""
        chunk = {
            'index': 12,
            'chapter': '第十二章',
            'content': '原文内容',
        }
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.delenv('NOVEL_ANALYSIS_SKIP_DISTILL', raising=False)

        def mock_llm(prompt: str) -> str:
            return '场景：X\n行动：Y\n变动：Z\n因果：W'

        result = rfe.distill_chunk_cached(chunk, llm_client=mock_llm)
        assert result['skipped'] is False
        assert result['scene'] == 'X'


# ─── 端到端集成验证 ────────────────────────────────────────────

class TestEndToEndDistillIntegration:
    """端到端验证：distill → build_user_message → S3 prompt 链路。"""

    def test_full_flow_with_distill(self, tmp_path, monkeypatch):
        """distill → build_user_message 完整链路（启用 distill）。"""
        chunk = {
            'index': 100,
            'chapter': '第一百章',
            'content': '莫凡进入魔法学院，开始学习初级魔法。',
        }
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.delenv('NOVEL_ANALYSIS_SKIP_DISTILL', raising=False)

        def mock_llm(prompt: str) -> str:
            return (
                '场景：魔法学院 入学日\n'
                '行动：莫凡报到注册\n'
                '变动：身份转变为学生\n'
                '因果：父母安排 → 进入学院'
            )

        # Step 1: distill
        distill_context = rfe.distill_chunk_cached(chunk, llm_client=mock_llm)
        assert distill_context['skipped'] is False
        assert distill_context['scene'] == '魔法学院 入学日'

        # Step 2: build_user_message with distill
        message = rfe.build_user_message(chunk, distill_context=distill_context)
        # 验证 prompt 中包含 distill 内容
        assert '魔法学院 入学日' in message
        # 也应包含原文（用于 S3 抽取）
        assert '莫凡进入魔法学院' in message

    def test_full_flow_with_skip(self, tmp_path, monkeypatch):
        """distill → build_user_message 完整链路（降级跳过）。"""
        chunk = {
            'index': 200,
            'chapter': '第二百章',
            'content': '原文内容XX',
        }
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.setenv('NOVEL_ANALYSIS_SKIP_DISTILL', '1')

        llm_mock = MagicMock(return_value='should not be called')

        # Step 1: distill（应被跳过）
        distill_context = rfe.distill_chunk_cached(chunk, llm_client=llm_mock)
        assert distill_context['skipped'] is True

        # Step 2: build_user_message（distill skipped，仍可用 raw_summary）
        message = rfe.build_user_message(chunk, distill_context=distill_context)
        # 跳过时 raw_summary 等于原文
        assert '原文内容XX' in message

        llm_mock.assert_not_called()
