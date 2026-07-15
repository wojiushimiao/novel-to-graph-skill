#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · 数据库写入器

锚定: L2_数据模型与核心算法.md §2.10
      L3_接口契约与约束.md §1.3.4 / 1.3.5 / 1.3.6

初始化 SQLite Schema 并批量写入实体和关系。
失败时事务回滚后抛 DatabaseWriteError。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from .models import (
    DatabaseWriteError,
    DB_WAL_MODE,
)

if TYPE_CHECKING:
    from .models import Entity, Relation

logger = logging.getLogger(__name__)

# Schema 文件路径（相对包根目录）
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "templates" / "schema.sql"


def init(db_path: str | Path) -> sqlite3.Connection:
    """初始化数据库表结构。

    执行 templates/schema.sql（6表+12索引+3视图）。

    Args:
        db_path: 数据库文件路径

    Returns:
        已初始化 Schema 的连接（已开启 WAL 模式）

    Raises:
        DatabaseWriteError: Schema 初始化失败
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(path))
        if DB_WAL_MODE:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")

        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()
        logger.info(f"数据库初始化完成: {path}")
        return conn
    except sqlite3.Error as exc:
        raise DatabaseWriteError(f"Schema 初始化失败: {exc}") from exc


def write_entities(
    conn: sqlite3.Connection,
    entities: "list[Entity]",
) -> int:
    """批量插入实体到 SQLite（UPSERT 语义）。

    Args:
        conn: 已初始化的数据库连接
        entities: 实体列表

    Returns:
        成功写入的行数

    Raises:
        DatabaseWriteError: 写入失败（事务已回滚）
    """
    if not entities:
        return 0

    count = 0
    try:
        with conn:  # 事务
            for entity in entities:
                conn.execute(
                    """INSERT OR REPLACE INTO entities
                    (id, name, type, base_info, detail_info, stitch_tags, coords,
                     importance_score, source_chapter, char_offset, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (
                        entity.id,
                        entity.name,
                        entity.type,
                        _to_json(entity.base_info),
                        _to_json(entity.detail_info),
                        _to_json(entity.stitch_tags),
                        _to_json(entity.coords),
                        float(entity.base_info.get("importance_score", 0.0)) if isinstance(entity.base_info, dict) else 0.0,
                        entity.source_chapter,
                        entity.char_offset,
                    ),
                )
                count += 1
        logger.info(f"实体写入完成: {count} 条")
        return count
    except sqlite3.Error as exc:
        logger.error(f"实体写入失败（事务回滚）: {exc}")
        raise DatabaseWriteError(f"实体写入失败: {exc}") from exc


def write_relations(
    conn: sqlite3.Connection,
    relations: "list[Relation]",
) -> int:
    """批量插入关系到 SQLite。

    Args:
        conn: 已初始化的数据库连接
        relations: 关系列表

    Returns:
        成功写入的行数

    Raises:
        DatabaseWriteError: 写入失败（事务已回滚）
    """
    if not relations:
        return 0

    count = 0
    try:
        with conn:
            for rel in relations:
                conn.execute(
                    """INSERT INTO wiki_relations
                    (source_id, target_id, relation_type, strength, description, source_chapter)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        rel.source_id,
                        rel.target_id,
                        rel.relation_type,
                        rel.strength,
                        rel.description,
                        rel.source_chapter,
                    ),
                )
                count += 1
        logger.info(f"关系写入完成: {count} 条")
        return count
    except sqlite3.Error as exc:
        logger.error(f"关系写入失败（事务回滚）: {exc}")
        raise DatabaseWriteError(f"关系写入失败: {exc}") from exc


def write_all(
    db_path: str | Path,
    entities: "list[Entity]",
    relations: "list[Relation]",
) -> sqlite3.Connection:
    """完整写入流程：初始化 + 实体 + 关系。

    Args:
        db_path: 数据库文件路径
        entities: 实体列表
        relations: 关系列表

    Returns:
        已写入数据的连接

    Raises:
        DatabaseWriteError: 任一步骤失败
    """
    conn = init(db_path)
    try:
        write_entities(conn, entities)
        write_relations(conn, relations)
        logger.info(f"完整写入完成: {len(entities)} 实体 + {len(relations)} 关系")
        return conn
    except DatabaseWriteError:
        conn.close()
        raise


def _to_json(value) -> str:
    """将任意值序列化为 JSON 字符串。"""
    if isinstance(value, str):
        # 已是 JSON 字符串：尝试解析后重新序列化确保合法性
        try:
            obj = json.loads(value)
            return json.dumps(obj, ensure_ascii=False)
        except json.JSONDecodeError:
            logger = logging.getLogger(__name__)
            logger.warning(f"_to_json: 非 JSON 字符串，自动包装: {value[:80]}...")
            return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)
