import json
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "material.db"
CONTROL_JSONL = Path(__file__).resolve().parent / "control.jsonl"

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
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""


class MaterialDB:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(DB_PATH)
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_QUERY_RESULTS_SQL)
        conn.commit()
        self._seed_from_jsonl()

    def _seed_from_jsonl(self) -> None:
        if not CONTROL_JSONL.exists():
            return
        lines = CONTROL_JSONL.read_text(encoding="utf-8").strip().splitlines()
        items = [json.loads(line) for line in lines]
        existing = {row["displayName"] for row in self.list_all()}
        new_items = [item for item in items if item["displayName"] not in existing]
        if new_items:
            self.batch_add(new_items, source="local")

    def add(self, item: dict, source: str = "local") -> None:
        conn = self._get_conn()
        conn.execute(
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
        conn.commit()

    def batch_add(self, items: list[dict], source: str = "local") -> None:
        conn = self._get_conn()
        conn.executemany(
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
        conn.commit()

    def search_by_name(self, keyword: str) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM controls WHERE displayName LIKE ?",
            (f"%{keyword}%",),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_all(self) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM controls ORDER BY displayName")
        return [dict(row) for row in cursor.fetchall()]

    def delete(self, display_name: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM controls WHERE displayName = ?", (display_name,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def clear_query_results(self) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM query_results")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='query_results'")
        conn.commit()

    def save_query_result(self, query: str, controls: list[dict]) -> None:
        conn = self._get_conn()
        conn.executemany(
            """INSERT INTO query_results (query, displayName, image, width, height)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    query,
                    c["displayName"],
                    c.get("image", ""),
                    c.get("width") or 0,
                    c.get("height") or 0,
                )
                for c in controls
            ],
        )
        conn.commit()

    def list_query_results(self, query: str = "") -> list[dict]:
        conn = self._get_conn()
        if query:
            cursor = conn.execute(
                "SELECT * FROM query_results WHERE query = ? ORDER BY id",
                (query,),
            )
        else:
            cursor = conn.execute("SELECT * FROM query_results ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]