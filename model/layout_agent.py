from __future__ import annotations

import asyncio
import json
import logging
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from model.canva_agent import (
    _calc_content_rect,
    _client,
    _schema_validate,
)
from model.get_background import generate_layout
from data.sqlite.material_db import MaterialDB

logger = logging.getLogger(__name__)

LAYOUT_DIR = _project_root / "layout"
_LOCK = asyncio.Lock()

@dataclass
class LayoutResult:
    json_data: dict
    content_rect: dict
    ir_data: dict
    nodes: list[dict]
    pipe_data: Optional[dict] = None


def _llm_text(resp) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    try:
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def _parse_json_lenient(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(text[s : e + 1])
        except Exception:
            pass
    return None


def _format_modified() -> str:
    now = datetime.now()
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{weekdays[now.weekday()]} {months[now.month - 1]} {now.day:02d} {now.year} {now.hour:02d}:{now.minute:02d}:{now.second:02d} GMT+0800 (中国标准时间)"


class LayoutAgent:
    def __init__(self, db=None, client=None, model=None, debug=False):
        self._db = db
        self._client = client if client is not None else _client
        self._model = model if model is not None else "deepseek-v4-flash"
        self._debug = debug

    async def create_canvas(
        self,
        title: Optional[str],
        width: int,
        height: int,
    ) -> dict:
        return generate_layout(title or "测试系统", width, height)

    async def generate(
        self,
        query: str,
        width: int,
        height: int,
        title: Optional[str] = None,
    ) -> LayoutResult:
        from model.generate_gird import generate_intent
        from model.compute_position import MissingMaterialError, convert_layout_file

        if self._db is None:
            raise ValueError("database required for position computation")
        materials = await self._db.list_query_results("")
        if not materials:
            raise MissingMaterialError("query_results 表为空")

        logger.info("Step 1/2: 并行生成背景画布和布局意图 IR...")
        canvas_task = asyncio.create_task(
            self.create_canvas(title, width, height)
        )
        intent_task = asyncio.create_task(
            generate_intent(query, materials, self._client, self._model)
        )
        canvas, layout_file = await asyncio.gather(canvas_task, intent_task)
        ir_data = layout_file.model_dump(exclude_none=True)

        logger.info("Step 3: 从 query_results 计算坐标...")
        nodes = convert_layout_file(ir_data, materials, width, height)

        if self._debug:
            position_path = LAYOUT_DIR / "position.json"
            position_path.parent.mkdir(parents=True, exist_ok=True)
            position_path.write_text(
                json.dumps(nodes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        logger.info("Step 4: 生成管线连接...")
        from model.get_connection import (
            generate_connections,
        )

        pipe_data = await generate_connections(
            query, nodes, self._client, self._model, ir_data
        )

        logger.info("Step 5: 拼装最终 JSON...")
        out = deepcopy(canvas)
        d = list(out.get("d", []))

        max_i = 0
        for n in d:
            i = n.get("i")
            if isinstance(i, int) and i > max_i:
                max_i = i

        for idx, node in enumerate(nodes):
            node["i"] = max_i + 1 + idx
            d.append(node)

        out["d"] = d

        flat = []
        for n in nodes:
            p = n.get("p", {})
            pos = p.get("position", {})
            flat.append({
                "x": pos.get("x", 0),
                "y": pos.get("y", 0),
                "width": p.get("width", 0) or 0,
                "height": p.get("height", 0) or 0,
                "displayName": p.get("displayName", ""),
            })
        out["contentRect"] = _calc_content_rect(flat)
        out["modified"] = _format_modified()

        errors = await _schema_validate(out)
        if errors:
            logger.warning("schema 校验失败: %s", errors)

        async with _LOCK:
            LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
            for filename, data in [
                ("it_ir.json", ir_data),
                ("pt_ir.json", nodes),
            ]:
                path = LAYOUT_DIR / filename
                tmp = path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(path)
            if pipe_data is not None:
                pipe_path = LAYOUT_DIR / "pipe.json"
                tmp = pipe_path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(pipe_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(pipe_path)

        return LayoutResult(
            json_data=out,
            content_rect=out["contentRect"],
            ir_data=ir_data,
            nodes=nodes,
            pipe_data=pipe_data,
        )


def _cli() -> None:
    title = input("title [测试系统]: ").strip() or "测试系统"
    query = input("query: ").strip()
    w = int(input("width [1920]: ").strip() or "1920")
    h = int(input("height [1080]: ").strip() or "1080")

    async def run() -> LayoutResult:
        db = MaterialDB()
        try:
            await db.init_query_results_db()
        except Exception:
            logger.exception("MaterialDB init failed")
        agent = LayoutAgent(db=db)
        return await agent.generate(query or "测试", w, h, title=title)

    result = asyncio.run(run())
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"layout_{ts}.json"
    out_path.write_text(
        json.dumps(result.json_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved: {out_path}")
    print(f"content_rect: {result.content_rect}")
    print(f"nodes: {len(result.nodes)}")


if __name__ == "__main__":
    _cli()
