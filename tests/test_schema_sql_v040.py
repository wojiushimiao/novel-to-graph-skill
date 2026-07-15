#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-A3 schema.sql v0.4.0 升级测试

锚定: track_A_plan.md §T-A3
检查点: CP-A3.1 (schema.sql 可执行) + CP-A3.2 (E_module CHECK 约束)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "templates" / "schema.sql"


@pytest.fixture
def db_connection():
    """创建内存 SQLite 数据库并执行 schema.sql。"""
    conn = sqlite3.connect(":memory:")
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    yield conn
    conn.close()


# ─── CP-A3.1: schema.sql 可执行无错误 ─────────────────────

class TestSchemaExecutable:
    """验证 schema.sql 可在 SQLite 3.35+ 中执行无错误。"""

    def test_schema_executes_without_error(self, db_connection):
        """schema.sql 执行无错误，所有表创建成功。"""
        cursor = db_connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        expected_tables = {"entities", "wiki_relations", "timeline_index", "events", "theme_clusters", "rules"}
        assert expected_tables.issubset(tables), f"缺少表: {expected_tables - tables}"

    def test_schema_file_exists(self):
        """schema.sql 文件存在。"""
        assert _SCHEMA_PATH.exists(), f"schema.sql 不存在于 {_SCHEMA_PATH}"


# ─── CP-A3.2: E_module 类型 CHECK 约束 ───────────────────

class TestEModuleCheckConstraint:
    """验证 E_module 类型 CHECK 约束生效。"""

    def test_insert_E_module_succeeds(self, db_connection):
        """插入 E_module 类型实体成功。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO entities (id, name, type) VALUES (?, ?, ?)",
            ("E_module_测试", "测试模块", "E_module"),
        )
        db_connection.commit()
        cursor.execute("SELECT type FROM entities WHERE id = ?", ("E_module_测试",))
        assert cursor.fetchone()[0] == "E_module"

    def test_insert_invalid_type_fails(self, db_connection):
        """插入非法 type 失败（CHECK 约束生效）。"""
        cursor = db_connection.cursor()
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO entities (id, name, type) VALUES (?, ?, ?)",
                ("X_非法", "非法实体", "invalid_type"),
            )

    def test_insert_existing_types_succeed(self, db_connection):
        """现有 8 类实体类型插入成功（向后兼容）。"""
        cursor = db_connection.cursor()
        existing_types = [
            "character", "location", "event", "item",
            "rule", "system", "monster", "knowledge",
        ]
        for idx, t in enumerate(existing_types):
            cursor.execute(
                "INSERT INTO entities (id, name, type) VALUES (?, ?, ?)",
                (f"{t}_{idx}", f"测试_{t}", t),
            )
        db_connection.commit()
        cursor.execute("SELECT COUNT(*) FROM entities WHERE type IN ('character','location','event','item','rule','system','monster','knowledge')")
        assert cursor.fetchone()[0] == 8


# ─── T_branch 关系类型约束 ─────────────────────────────────

class TestTBranchCheckConstraint:
    """验证 T_branch 关系类型 CHECK 约束（已在 v0.3.0 存在，v0.4.0 确认保留）。"""

    def test_insert_T_branch_succeeds(self, db_connection):
        """插入 T_branch 类型关系成功。"""
        cursor = db_connection.cursor()
        # 先插入两个 E_module 实体
        cursor.execute("INSERT INTO entities (id, name, type) VALUES (?, ?, ?)", ("E_module_1", "模块1", "E_module"))
        cursor.execute("INSERT INTO entities (id, name, type) VALUES (?, ?, ?)", ("E_module_2", "模块2", "E_module"))
        # 插入 T_main 关系
        cursor.execute(
            "INSERT INTO wiki_relations (source_id, target_id, relation_type) VALUES (?, ?, ?)",
            ("E_module_1", "E_module_2", "T_main"),
        )
        db_connection.commit()
        cursor.execute("SELECT relation_type FROM wiki_relations WHERE source_id = ?", ("E_module_1",))
        assert cursor.fetchone()[0] == "T_main"


# ─── info 字段新增验证 ─────────────────────────────────────

class TestInfoField:
    """验证 v0.4.0 新增的 info 字段。"""

    def test_info_field_exists(self, db_connection):
        """entities 表有 info 字段。"""
        cursor = db_connection.cursor()
        cursor.execute("PRAGMA table_info(entities)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "info" in columns, "entities 表必须有 info 字段（v0.4.0 新增）"

    def test_insert_with_info(self, db_connection):
        """插入带 info 的实体成功。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO entities (id, name, type, info) VALUES (?, ?, ?, ?)",
            ("E_module_测试", "测试模块", "E_module", "a" * 800),
        )
        db_connection.commit()
        cursor.execute("SELECT info FROM entities WHERE id = ?", ("E_module_测试",))
        assert len(cursor.fetchone()[0]) == 800


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
