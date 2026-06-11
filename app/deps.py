from __future__ import annotations

from typing import Optional

from app.config import settings
from data.chroma import ControlChunk
from data.material_db import MaterialDB
from model.canva_agent import CanvasAgent
from model.control_agent import ControlAgent

_control_agent: Optional[ControlAgent] = None
_canvas_agent: Optional[CanvasAgent] = None
_material_db: Optional[MaterialDB] = None
_chroma_watcher: Optional[ControlChunk] = None


async def init_resources() -> None:
    global _material_db, _control_agent, _canvas_agent, _chroma_watcher

    db = MaterialDB()
    await db.init_db()
    _material_db = db

    agent = ControlAgent(db=db)
    await agent.init()
    _control_agent = agent

    _canvas_agent = CanvasAgent(db=db)

    _chroma_watcher = ControlChunk(control_jsonl_path=settings.control_jsonl_path)
    _chroma_watcher.check_and_reseed()
    _chroma_watcher.start_watcher()


async def close_resources() -> None:
    global _material_db, _chroma_watcher
    if _chroma_watcher is not None:
        _chroma_watcher.stop_watcher()
        _chroma_watcher = None
    if _material_db is not None:
        await _material_db.close()


def get_control_agent() -> ControlAgent:
    assert _control_agent is not None, "ControlAgent not initialized (call init_resources first)"
    return _control_agent


def get_canvas_agent() -> CanvasAgent:
    assert _canvas_agent is not None, "CanvasAgent not initialized (call init_resources first)"
    return _canvas_agent


def get_material_db() -> MaterialDB:
    assert _material_db is not None, "MaterialDB not initialized (call init_resources first)"
    return _material_db
