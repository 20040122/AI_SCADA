from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "material.db"
CONTROL_JSONL = Path(__file__).resolve().parent.parent / "control.jsonl"

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS controls (
    displayName TEXT PRIMARY KEY,
    image TEXT NOT NULL,
    width REAL,
    height REAL,
    source TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

_CREATE_QUERY_RESULTS_SQL = """\
CREATE TABLE IF NOT EXISTS query_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    displayName TEXT NOT NULL,
    image TEXT,
    width REAL,
    height REAL,
    similarity REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'vector',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""


class MaterialDB:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(DB_PATH)
        self._conn: Optional[aiosqlite.Connection] = None
        self._jsonl_hash = ""

    def _compute_jsonl_hash(self) -> str:
        if not CONTROL_JSONL.exists():
            return ""
        return hashlib.sha256(CONTROL_JSONL.read_bytes()).hexdigest()

    async def sync_if_needed(self) -> None:
        current_hash = self._compute_jsonl_hash()
        if current_hash and current_hash != self._jsonl_hash:
            logger.info("control.jsonl 已变更，同步 SQLite...")
            await self._seed_from_jsonl()
            self._jsonl_hash = current_hash

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    async def init_db(self) -> None:
        conn = await self._get_conn()
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.execute(_CREATE_QUERY_RESULTS_SQL)
        await self._migrate_query_results(conn)
        await conn.commit()

        self._jsonl_hash = self._compute_jsonl_hash()
        await self._seed_from_jsonl()
        self._jsonl_hash = self._compute_jsonl_hash()

    async def init_query_results_db(self) -> None:
        conn = await self._get_conn()
        await conn.execute(_CREATE_QUERY_RESULTS_SQL)
        await self._migrate_query_results(conn)
        await conn.commit()

    async def _migrate_query_results(self, conn: aiosqlite.Connection) -> None:
        cursor = await conn.execute("PRAGMA table_info(query_results)")
        rows = await cursor.fetchall()
        cols = {row[1] for row in rows}
        if "similarity" not in cols:
            await conn.execute("ALTER TABLE query_results ADD COLUMN similarity REAL NOT NULL DEFAULT 0.0")
        if "source" not in cols:
            await conn.execute("ALTER TABLE query_results ADD COLUMN source TEXT NOT NULL DEFAULT 'vector'")

    async def _seed_from_jsonl(self) -> None:
        if not CONTROL_JSONL.exists():
            return
        lines = CONTROL_JSONL.read_text(encoding="utf-8").strip().splitlines()
        items = [json.loads(line) for line in lines]

        existing = await self.list_all()
        existing_names = {row["displayName"] for row in existing}
        jsonl_names = {item["displayName"] for item in items}

        stale_names = existing_names - jsonl_names
        for name in stale_names:
            await self.delete(name)
        if stale_names:
            logger.info("SQLite 移除 %d 个已删除控件", len(stale_names))

        await self.batch_add(items, source="local")

    async def add(self, item: dict, source: str = "local") -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO controls (displayName, image, width, height, source)
               VALUES (?, ?, ?, ?, ?)""",
            (
                item["displayName"],
                item["image"],
                item.get("width") or 0,
                item.get("height") or 0,
                source,
            ),
        )
        await conn.commit()

    async def confirm_generated(self, name: str, image: str, query: str) -> None:
        conn = await self._get_conn()
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.execute(_CREATE_QUERY_RESULTS_SQL)
        await conn.execute(
            """INSERT OR REPLACE INTO controls (displayName, image, width, height, source)
               VALUES (?, ?, ?, ?, ?)""",
            (name, image, 128, 128, "ai-generated"),
        )
        await conn.execute(
            """INSERT INTO query_results (query, displayName, image, width, height, similarity, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (query, name, image, 128, 128, 1.0, "ai-generated"),
        )
        await conn.commit()

    async def batch_add(self, items: list[dict], source: str = "local") -> None:
        conn = await self._get_conn()
        await conn.executemany(
            """INSERT OR REPLACE INTO controls (displayName, image, width, height, source)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    item["displayName"],
                    item["image"],
                    item.get("width") or 0,
                    item.get("height") or 0,
                    source,
                )
                for item in items
            ],
        )
        await conn.commit()

    async def search_by_name(self, keyword: str) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM controls WHERE displayName LIKE ?",
            (f"%{keyword}%",),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_all(self) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT * FROM controls ORDER BY displayName")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete(self, display_name: str) -> bool:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "DELETE FROM controls WHERE displayName = ?", (display_name,)
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def clear_query_results(self) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM query_results")
        await conn.execute("DELETE FROM sqlite_sequence WHERE name='query_results'")
        await conn.commit()

    async def save_query_result(self, query: str, controls: list[dict]) -> int:
        conn = await self._get_conn()
        await conn.executemany(
            """INSERT INTO query_results (query, displayName, image, width, height, similarity, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    query,
                    c["displayName"],
                    c.get("image", ""),
                    c.get("width") or 0,
                    c.get("height") or 0,
                    c.get("similarity", 0.0),
                    c.get("source", "vector"),
                )
                for c in controls
            ],
        )
        await conn.commit()
        return len(controls)

    async def get_latest_query(self) -> Optional[str]:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT query FROM query_results ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        return row["query"] if row else None

    async def search_query_results_by_name(self, keyword: str) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM query_results WHERE displayName LIKE ? ORDER BY id",
            (f"%{keyword}%",),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_query_results(self, query: str = "") -> list[dict]:
        conn = await self._get_conn()
        if query:
            cursor = await conn.execute(
                "SELECT * FROM query_results WHERE query = ? ORDER BY id",
                (query,),
            )
        else:
            cursor = await conn.execute("SELECT * FROM query_results ORDER BY id DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
