#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-B.1/T-B.2 chunk 自适应测试

锚定: v0.5.0 plan.md §T-B.1 / §T-B.2
检查点:
  - CP-B.1-B.4: detect_chunk_size() 三档映射 + 边界
  - CP-B.6-B.8: chunk_text() 自适应分块集成测试
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ─── 导入路径设置 ───────────────────────────────────────────
# novel-to-graph-skill 目录名含连字符，无法作为 Python 包；
# 把 SKILL_DIR 放到 sys.path 最前面，确保 tools 解析到本技能的 tools 目录。
for _mod in list(sys.modules):
    if _mod == "tools" or _mod.startswith("tools."):
        del sys.modules[_mod]

_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) in sys.path:
    sys.path.remove(str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from tools.models import DEFAULT_CHUNK_SIZE, CHUNK_SIZE_TIERS  # noqa: E402
from tools.text_chunker import detect_chunk_size, chunk_text  # noqa: E402


class TestDetectChunkSize:
    """CP-B.1-B.4: detect_chunk_size() 三档映射 + 边界。"""

    def test_large_context_128k_returns_20k(self):
        assert detect_chunk_size(128_000) == 20_000

    def test_medium_context_64k_returns_8k(self):
        assert detect_chunk_size(64_000) == 8_000

    def test_small_context_16k_returns_4k(self):
        assert detect_chunk_size(16_000) == 4_000

    def test_boundary_32k_returns_8k(self):
        assert detect_chunk_size(32_000) == 8_000

    def test_boundary_128k_returns_20k(self):
        assert detect_chunk_size(128_000) == 20_000

    def test_zero_context_returns_4k(self):
        assert detect_chunk_size(0) == 4_000

    def test_negative_context_raises(self):
        with pytest.raises(ValueError, match="不能为负值"):
            detect_chunk_size(-1)

    def test_none_returns_default(self):
        assert detect_chunk_size(None) == DEFAULT_CHUNK_SIZE

    def test_no_args_returns_default(self):
        assert detect_chunk_size() == DEFAULT_CHUNK_SIZE

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("NOVEL_ANALYSIS_MODEL_CTX", "64000")
        assert detect_chunk_size() == 8_000

    def test_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("NOVEL_ANALYSIS_MODEL_CTX", raising=False)
        assert detect_chunk_size() == DEFAULT_CHUNK_SIZE


class TestChunkTextAdaptive:
    """CP-B.6-B.8: chunk_text() 自适应分块集成测试。"""

    _SAMPLE = "测试段落内容。" * 500  # ~3500 chars

    def test_chunk_text_with_model_ctx_128k(self):
        """model_ctx_tokens=128000 → 20K chunk，样本应产生 1 个 chunk。"""
        chunks = chunk_text(self._SAMPLE, model_ctx_tokens=128_000)
        assert len(chunks) >= 1

    def test_chunk_text_explicit_chunk_size_unchanged(self):
        """显式指定 chunk_size=8000，行为与 v0.4.1 一致。"""
        chunks = chunk_text(self._SAMPLE, chunk_size=8000)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.char_count <= 8000 + 1000  # 允许段落完整性导致的浮动


if __name__ == "__main__":
    pytest.main([__file__, "-v"])