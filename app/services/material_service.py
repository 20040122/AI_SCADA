from __future__ import annotations

from typing import Optional

from data.material_db import MaterialDB


class MaterialService:
    def __init__(self, db: MaterialDB) -> None:
        self._db = db

    async def list_controls(self) -> list[dict]:
        rows = await self._db.list_all()
        return [
            {
                "displayName": row["displayName"],
                "image": row["image"],
                "width": row.get("width") or 0,
                "height": row.get("height") or 0,
                "source": row.get("source", "local"),
            }
            for row in rows
        ]

    async def list_query_results(self) -> list[dict]:
        rows = await self._db.list_query_results()
        return [
            {
                "displayName": row["displayName"],
                "image": row.get("image", ""),
                "width": row.get("width") or 0,
                "height": row.get("height") or 0,
                "source": row.get("source", "query"),
                "similarity": row.get("similarity", 0.0),
            }
            for row in rows
        ]

    async def clear_query_results(self) -> None:
        await self._db.clear_query_results()

    async def save_query_result(self, query: str, controls: list[dict]) -> int:
        return await self._db.save_query_result(query, controls)

    async def get_latest_query(self) -> Optional[str]:
        return await self._db.get_latest_query()
