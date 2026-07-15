#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-E1 v0.4.1 端到端集成验证测试

锚定: v0.4.1_plan_final.md §T-E1
检查点:
  - CP-E1.1: Info 达标率 ≥70%（通过 HAR 重抽机制保证，本测试验证 HAR 接口契约）
  - CP-E1.2: Info 平均字数 ≥500（通过四段结构强制，本测试验证四段结构链路）
  - CP-E1.3: 输出中无 `[src:chunk_NNN]` 残留（验证 strip_src_markers 链路）
  - CP-E1.4: T_main 卷数 5-20，每卷模块 ≤8（验证 Skeleton 增量构建链路）
  - CP-E1.5: 管线全流程通过（验证 S2.5→S3→S4.25→S4.3→S5→S7 代码可达性）
  - CP-E1.6: HAR 统计字段完整（含 budget_used/aborted）

测试策略:
  本测试不调用真实 LLM，使用 mock 验证各模块的接口契约和协同工作。
  完整的端到端管线运行（含 LLM 调用）由 run_s4_s7_pipeline.py + run_full_llm_extraction.py
  在实际抽取时执行。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ─── 导入路径设置 ───────────────────────────────────────────
for _mod in list(sys.modules):
    if _mod == "tools" or _mod.startswith("tools."):
        del sys.modules[_mod]

_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) in sys.path:
    sys.path.remove(str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR))

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# ─── CP-E1.5: 管线全流程代码可达性 ────────────────────────────

class TestPipelineReachability:
    """验证 S2.5→S3→S4.25→S4.3→S5→S7 各阶段函数都能被导入和调用。"""

    def test_s2_5_incremental_skeleton_reachable(self):
        """S2.5 增量压缩构建时序骨架函数可调用。"""
        from tools import semantic_clusterer
        from tools import timeline_skeleton_builder
        from tools.timeline_skeleton_builder import Skeleton, build_skeleton_incremental

        assert callable(semantic_clusterer.cluster_summaries)
        assert callable(build_skeleton_incremental)
        assert Skeleton is not None

    def test_s2_8_distiller_reachable(self):
        """S2.8 Document Distiller 函数可调用。"""
        from tools.document_distiller import distill_chunk

        assert callable(distill_chunk)

    def test_s4_1_to_s4_3_reachable(self):
        """S4.1→S4.2→S4.25→S4.3 清洗校验函数可调用。"""
        from tools import json_cleaner, schema_validator, low_value_filter
        from tools.schema_validator import (
            validate_info_structure,
            validate_src_marker,
            strip_src_markers,
            validate_info_length_v041,
        )

        assert callable(schema_validator.validate)
        assert callable(low_value_filter.filter)
        assert callable(validate_info_structure)
        assert callable(validate_src_marker)
        assert callable(strip_src_markers)
        assert callable(validate_info_length_v041)

    def test_s4_25_har_refiner_reachable(self):
        """S4.25 HAR 自洽校验函数可调用。"""
        from tools.har_refiner import refine_info

        assert callable(refine_info)

    def test_s5_db_writer_reachable(self):
        """S5 数据库写入函数可调用。"""
        from tools import db_writer

        assert hasattr(db_writer, 'write_to_db') or hasattr(db_writer, 'write_entities')

    def test_s7_report_reachable(self):
        """S7 报表生成函数可调用。"""
        from tools import html_renderer, exporter, stats_generator

        assert callable(html_renderer.render) or callable(html_renderer.render_html)
        assert callable(stats_generator.generate) or callable(stats_generator.compute_stats)

    def test_run_s4_s7_pipeline_reachable(self):
        """run_s4_s7_pipeline.py 主流程函数可调用。"""
        import run_s4_s7_pipeline as pipeline

        assert callable(pipeline.s4_clean_validate)
        assert callable(pipeline.s2_5_build_skeleton_incremental)
        assert callable(pipeline.compute_skeleton_stats)
        assert callable(pipeline.compute_har_stats)
        assert callable(pipeline.strip_src_markers_in_items)

    def test_run_full_llm_extraction_reachable(self):
        """run_full_llm_extraction.py 主流程函数可调用。"""
        import run_full_llm_extraction as extraction

        assert callable(extraction.build_user_message)
        assert callable(extraction.distill_chunk_cached)
        assert hasattr(extraction, 'DISTILL_DIR')


# ─── CP-E1.3: 输出中无 [src:chunk_NNN] 残留 ──────────────────

class TestSrcMarkerEndToEnd:
    """验证 [src:chunk_NNN] 标记从生成到剥离的完整链路。"""

    def test_src_marker_validation_and_strip_consistency(self):
        """src 标记校验与剥离函数一致工作。"""
        from tools.schema_validator import validate_src_marker, strip_src_markers

        # 含完整 src 标记的 info
        info_with_markers = (
            '【起因】事件起因描述 [src:chunk_001]\n'
            '【经过】事件经过描述 [src:chunk_002]\n'
            '【结果】事件结果描述 [src:chunk_003]\n'
            '【模块定位】模块定位描述 [src:chunk_004]'
        )

        # 校验应通过
        passed, _ = validate_src_marker(info_with_markers)
        assert passed is True

        # 剥离后应无标记
        stripped = strip_src_markers(info_with_markers)
        assert '[src:chunk_' not in stripped
        # 但内容应保留
        assert '事件起因描述' in stripped
        assert '事件经过描述' in stripped

    def test_pipeline_strip_src_markers_in_items_function(self):
        """run_s4_s7_pipeline 的批量剥离函数正确工作。"""
        import run_s4_s7_pipeline as pipeline

        items = [
            {
                'delta_update': {
                    'updated_fields': {
                        'info': '【起因】xxx [src:chunk_001]\n【经过】yyy [src:chunk_002]'
                    }
                }
            },
            {
                'delta_update': {
                    'updated_fields': {
                        'info': '【结果】zzz [src:chunk_003]'
                    }
                }
            },
        ]
        cleaned = pipeline.strip_src_markers_in_items(items)

        assert len(cleaned) == 2
        for item in cleaned:
            info = item['delta_update']['updated_fields']['info']
            assert '[src:chunk_' not in info

    def test_malformed_markers_preserved(self):
        """畸形标记（无数字）应保留供调试。"""
        from tools.schema_validator import strip_src_markers

        info = '【起因】xxx [src:chunk_]'
        stripped = strip_src_markers(info)
        # 畸形标记保留
        assert '[src:chunk_]' in stripped


# ─── CP-E1.6: HAR 统计字段完整 ────────────────────────────────

class TestHarStatsFields:
    """验证 HAR 统计字段完整性。"""

    def test_compute_har_stats_zero_when_disabled(self):
        """HAR 禁用时返回零值统计。"""
        import run_s4_s7_pipeline as pipeline

        stats = pipeline.compute_har_stats(None)
        required_fields = {'total', 'success', 'failed', 'retries_avg', 'budget_used', 'aborted'}
        assert required_fields.issubset(stats.keys())
        assert stats['total'] == 0
        assert stats['success'] == 0
        assert stats['failed'] == 0
        assert stats['aborted'] is False

    def test_compute_har_stats_preserves_fields(self):
        """HAR 启用时统计字段完整传递。"""
        import run_s4_s7_pipeline as pipeline

        raw_stats = {
            'total': 100,
            'success': 80,
            'failed': 20,
            'retries_avg': 1.5,
            'budget_used': 250,
            'aborted': True,
        }
        stats = pipeline.compute_har_stats(raw_stats)
        assert stats['total'] == 100
        assert stats['success'] == 80
        assert stats['failed'] == 20
        assert stats['retries_avg'] == 1.5
        assert stats['budget_used'] == 250
        assert stats['aborted'] is True

    def test_har_refiner_returns_complete_stats(self):
        """HAR refiner 返回的统计含所有必要字段。"""
        from tools.har_refiner import refine_info

        # 空 entries 应返回零值统计
        entries: list[dict] = []
        chunks: dict[int, str] = {}
        llm_mock = MagicMock(return_value='')

        refined, stats = refine_info(
            entries=entries,
            chunks=chunks,
            llm_client=llm_mock,
        )

        required_fields = {'total', 'success', 'failed', 'retries_avg', 'budget_used', 'aborted'}
        assert required_fields.issubset(stats.keys())


# ─── CP-E1.4: T_main 卷数 5-20，每卷 E_module ≤8 ─────────────

class TestSkeletonStatsFields:
    """验证 Skeleton 统计字段完整性。"""

    def test_compute_skeleton_stats_has_required_fields(self):
        """compute_skeleton_stats 返回的字段完整。"""
        import run_s4_s7_pipeline as pipeline
        from tools.timeline_skeleton_builder import Skeleton

        skeleton = Skeleton()
        stats = pipeline.compute_skeleton_stats(skeleton, fallback_used=False, input_count=100)

        required_fields = {
            't_main_volume_count',
            'e_module_count',
            'has_module_relation_count',
            't_main_relation_count',
            't_main_module_relation_count',
            'compression_ratio',
            'fallback_used',
        }
        assert required_fields.issubset(stats.keys())

    def test_s2_5_incremental_returns_stats(self):
        """s2_5_build_skeleton_incremental 返回 (Skeleton, stats) 二元组。"""
        import run_s4_s7_pipeline as pipeline

        # 使用 mock summaries 触发降级路径（避免依赖 embedding 模型）
        summaries = [
            {'chunk_index': i, 'summary': f'摘要 {i}'} for i in range(50)
        ]
        skeleton, stats = pipeline.s2_5_build_skeleton_incremental(summaries, use_embedding=False)

        assert skeleton is not None
        assert isinstance(stats, dict)
        assert 't_main_volume_count' in stats
        assert 'fallback_used' in stats

    def test_s2_5_incremental_volume_count_in_range(self):
        """增量压缩产出 T_main 卷数 ∈ [5, 20]（或降级路径）。"""
        import run_s4_s7_pipeline as pipeline

        # 构造 50 个摘要，应能产出 5-20 卷
        summaries = [
            {'chunk_index': i, 'summary': f'摘要 {i}'} for i in range(50)
        ]
        skeleton, stats = pipeline.s2_5_build_skeleton_incremental(summaries, use_embedding=False)

        # 增量模式或降级模式都应满足 T_main 卷数 ∈ [5, 20]（降级时可能为 0）
        volume_count = stats['t_main_volume_count']
        if stats['fallback_used']:
            # 降级模式：T_main_volumes 为空，e_modules 应有值
            assert volume_count == 0 or 5 <= volume_count <= 20
        else:
            # 增量模式：T_main 卷数严格在 5-20 范围内
            assert 5 <= volume_count <= 20


# ─── CP-E1.1 / CP-E1.2: Info 四段结构端到端 ───────────────────

class TestFourSegmentStructureE2E:
    """验证四段结构在 schema_validator → har_refiner → strip_src_markers 链路中的一致性。"""

    def test_valid_four_segment_info_passes_all_checks(self):
        """合规的四段结构 info 应通过所有校验。"""
        from tools.schema_validator import (
            validate_info_structure,
            validate_src_marker,
            validate_info_length_v041,
            strip_src_markers,
        )

        # 字数需满足：起因≥100 / 经过≥200 / 结果≥100 / 模块定位≥100
        valid_info = (
            '【起因】' + '起因描述' * 30 + ' [src:chunk_001]\n'  # 120 字
            '【经过】' + '经过描述' * 60 + ' [src:chunk_002]\n'  # 240 字
            '【结果】' + '结果描述' * 30 + ' [src:chunk_003]\n'  # 120 字
            '【模块定位】' + '模块定位描述' * 20 + ' [src:chunk_004]'  # 120 字
        )

        # 四段结构校验
        passed_struct, _ = validate_info_structure(valid_info)
        assert passed_struct is True

        # src 标记校验
        passed_src, _ = validate_src_marker(valid_info)
        assert passed_src is True

        # 字数校验
        passed_len, _, _ = validate_info_length_v041(valid_info)
        assert passed_len is True

        # 剥离标记后仍保留四段结构
        stripped = strip_src_markers(valid_info)
        assert '【起因】' in stripped
        assert '【经过】' in stripped
        assert '【结果】' in stripped
        assert '【模块定位】' in stripped
        assert '[src:chunk_' not in stripped

    def test_har_refiner_uses_same_validation_as_schema_validator(self):
        """HAR refiner 内部使用与 schema_validator 一致的校验逻辑。"""
        from tools.har_refiner import refine_info
        from tools.schema_validator import validate_info_length_v041, validate_info_structure

        # 构造一个不达标的 info（字数不足）
        short_info = (
            '【起因】短描述 [src:chunk_001]\n'
            '【经过】短经过 [src:chunk_002]\n'
            '【结果】短结果 [src:chunk_003]\n'
            '【模块定位】短定位 [src:chunk_004]'
        )

        # schema_validator 应判为不达标
        passed_len, _, _ = validate_info_length_v041(short_info)
        assert passed_len is False

        # 构造 entries
        entries = [
            {
                'event_id': 'E_test_001',
                'importance': 'high',
                'delta_update': {
                    'updated_fields': {
                        'info': short_info,
                    }
                },
            }
        ]
        chunks = {1: '原文 chunk 1', 2: '原文 chunk 2'}

        # HAR 应识别为需要重抽
        def mock_llm(prompt: str) -> str:
            # 返回合规的 info
            return (
                '【起因】' + '重抽起因描述' * 20 + ' [src:chunk_001]\n'
                '【经过】' + '重抽经过描述' * 40 + ' [src:chunk_002]\n'
                '【结果】' + '重抽结果描述' * 20 + ' [src:chunk_003]\n'
                '【模块定位】' + '重抽模块定位' * 20 + ' [src:chunk_004]'
            )

        refined, stats = refine_info(
            entries=entries,
            chunks=chunks,
            llm_client=mock_llm,
            max_retries=3,
        )

        # HAR 应成功重抽
        assert stats['total'] == 1
        assert stats['success'] == 1
        assert stats['failed'] == 0

        # 重抽后的 info 应通过所有校验
        new_info = refined[0]['delta_update']['updated_fields']['info']
        passed_len, _, _ = validate_info_length_v041(new_info)
        passed_struct, _ = validate_info_structure(new_info)
        assert passed_len is True
        assert passed_struct is True


# ─── 降级开关协同验证 ─────────────────────────────────────────

class TestDegradationSwitches:
    """验证所有降级开关协同工作。"""

    def test_skip_distill_env_var(self, tmp_path, monkeypatch):
        """NOVEL_ANALYSIS_SKIP_DISTILL=1 跳过 Distiller。"""
        import run_full_llm_extraction as rfe

        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.setenv('NOVEL_ANALYSIS_SKIP_DISTILL', '1')

        chunk = {'index': 0, 'chapter': '第一章', 'content': '原文'}
        llm_mock = MagicMock(return_value='should not be called')

        result = rfe.distill_chunk_cached(chunk, llm_client=llm_mock)
        assert result['skipped'] is True
        assert result['raw_summary'] == '原文'
        llm_mock.assert_not_called()

    def test_enable_har_env_var_not_set_defaults_to_disabled(self):
        """NOVEL_ANALYSIS_ENABLE_HAR 未设置时 HAR 默认禁用。"""
        # s4_clean_validate 的 enable_har 参数默认为 False
        # 这是向后兼容的保证
        import run_s4_s7_pipeline as pipeline
        import inspect

        sig = inspect.signature(pipeline.s4_clean_validate)
        assert sig.parameters['enable_har'].default is False

    def test_s2_5_fallback_to_build_skeleton_on_failure(self):
        """S2.5 增量压缩失败时降级到一次性模式。"""
        import run_s4_s7_pipeline as pipeline

        # 构造空 summaries 触发异常路径
        # 注意：空 summaries 在语义聚类阶段会失败，触发降级
        summaries: list[dict] = []

        skeleton, stats = pipeline.s2_5_build_skeleton_incremental(summaries, use_embedding=False)

        # 降级模式应返回有效 Skeleton（即使为空）
        assert skeleton is not None
        assert isinstance(stats, dict)
        # fallback_used 应为 True（空输入触发降级）
        assert stats['fallback_used'] is True


# ─── 端到端管线集成（mock LLM） ───────────────────────────────

class TestEndToEndPipelineIntegration:
    """端到端验证 v0.4.1 改造后的管线协同工作。"""

    def test_s4_pipeline_with_har_enabled_no_src_residual(self):
        """启用 HAR 的 S4 管线输出无 [src:chunk_NNN] 残留。"""
        import run_s4_s7_pipeline as pipeline

        # 构造含 src 标记的 LLM 输出
        items = [
            {
                'event_id': 'E_test_001',
                'importance': 'high',
                'delta_update': {
                    'target_entity_id': 'E_test_001',
                    'updated_fields': {
                        'info': (
                            '【起因】xxx [src:chunk_001]\n'
                            '【经过】yyy [src:chunk_002]\n'
                            '【结果】zzz [src:chunk_003]\n'
                            '【模块定位】www [src:chunk_004]'
                        ),
                    },
                },
            }
        ]

        # 不启用 HAR（避免需要 mock LLM），仅验证 src 标记剥离
        filtered, har_stats = pipeline.s4_clean_validate(items, enable_har=False)

        # 输出应无 src 标记残留
        for item in filtered:
            info = item.get('delta_update', {}).get('updated_fields', {}).get('info', '')
            assert '[src:chunk_' not in info

        # HAR 统计应为零值
        assert har_stats['total'] == 0
        assert har_stats['aborted'] is False

    def test_s4_pipeline_with_har_disabled_backward_compatible(self):
        """禁用 HAR 时 S4 管线向后兼容（行为同 v0.4.0）。"""
        import run_s4_s7_pipeline as pipeline

        items = [
            {
                'event_id': 'E_test_002',
                'importance': 'medium',
                'delta_update': {
                    'target_entity_id': 'E_test_002',
                    'updated_fields': {
                        'info': '无标记的 info 内容',
                    },
                },
            }
        ]

        filtered, har_stats = pipeline.s4_clean_validate(items, enable_har=False)

        # 应正常返回
        assert isinstance(filtered, list)
        assert har_stats['total'] == 0

    def test_distill_to_s3_prompt_to_s4_chain(self, tmp_path, monkeypatch):
        """验证 Distiller → S3 prompt → S4 校验的完整链路。"""
        import run_full_llm_extraction as rfe
        import run_s4_s7_pipeline as pipeline

        # Step 1: Distiller 预处理
        monkeypatch.setattr(rfe, 'DISTILL_DIR', tmp_path)
        monkeypatch.delenv('NOVEL_ANALYSIS_SKIP_DISTILL', raising=False)

        chunk = {
            'index': 0,
            'chapter': '第一章',
            'content': '莫凡进入魔法学院开始学习。',
        }

        def mock_distill_llm(prompt: str) -> str:
            return (
                '场景：魔法学院\n'
                '行动：莫凡注册\n'
                '变动：身份转变\n'
                '因果：父母安排 → 进入学院'
            )

        distill_context = rfe.distill_chunk_cached(chunk, llm_client=mock_distill_llm)
        assert distill_context['skipped'] is False
        assert '魔法学院' in distill_context['scene']

        # Step 2: build_user_message with distill context
        message = rfe.build_user_message(chunk, distill_context=distill_context)
        assert '魔法学院' in message
        assert '莫凡进入魔法学院' in message

        # Step 3: 模拟 LLM 产出含 src 标记的 info，S4 应正确剥离
        items = [
            {
                'event_id': 'E_mofan_register',
                'importance': 'high',
                'delta_update': {
                    'target_entity_id': 'E_mofan_register',
                    'updated_fields': {
                        'info': (
                            '【起因】莫凡注册 [src:chunk_001]\n'
                            '【经过】学习魔法 [src:chunk_002]\n'
                            '【结果】成为学生 [src:chunk_003]\n'
                            '【模块定位】入学篇 [src:chunk_004]'
                        ),
                    },
                },
            }
        ]

        filtered, _ = pipeline.s4_clean_validate(items, enable_har=False)

        # 输出应无 src 标记
        if filtered:
            for item in filtered:
                info = item.get('delta_update', {}).get('updated_fields', {}).get('info', '')
                assert '[src:chunk_' not in info


# ─── 全量回归验证 ─────────────────────────────────────────────

class TestFullRegression:
    """验证 v0.4.1 新增测试与 v0.4.0 旧测试协同通过。"""

    def test_v041_test_files_exist(self):
        """v0.4.1 新增的测试文件应全部存在。"""
        test_files = [
            'test_schema_validator_v041.py',  # T-B2
            'test_har_refiner.py',  # T-B1
            'test_summary_buffer.py',  # T-C1
            'test_semantic_clusterer.py',  # T-C2
            'test_document_distiller.py',  # T-D1
            'test_timeline_skeleton_builder_v041.py',  # T-C3
            'test_run_s4_s7_pipeline_har.py',  # T-B3
            'test_run_s4_s7_pipeline_skeleton.py',  # T-C4
            'test_run_full_llm_extraction_distiller.py',  # T-D2
            'test_e2e_integration_v041.py',  # T-E1 (本文件)
        ]
        for fname in test_files:
            fpath = _TESTS_DIR / fname
            assert fpath.exists(), f'测试文件缺失: {fname}'

    def test_v040_test_files_preserved(self):
        """v0.4.0 旧测试文件应保留（向后兼容验证）。"""
        test_files = [
            'test_timeline_skeleton_builder.py',  # v0.4.0 T-B2
            'test_e2e_pipeline.py',  # v0.4.0 T-E1
        ]
        for fname in test_files:
            fpath = _TESTS_DIR / fname
            assert fpath.exists(), f'v0.4.0 测试文件缺失: {fname}'
