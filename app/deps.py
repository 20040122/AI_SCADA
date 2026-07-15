from __future__ import annotations

from typing import Optional

from app.config import settings
from data.chroma import ControlChunk
from data.sqlite.material_db import MaterialDB
from model import search_service as search_svc
from model.control_agent import ControlAgent
from model.layout_agent import LayoutAgent

_control_agent: Optional[ControlAgent] = None
_layout_agent: Optional[LayoutAgent] = None
_material_db: Optional[MaterialDB] = None
_chroma_watcher: Optional[ControlChunk] = None


async def init_resources() -> None:
    global _material_db, _control_agent, _layout_agent, _chroma_watcher

    db = MaterialDB()
    await db.init_db()
    _material_db = db

    agent = ControlAgent(db=db)
    await agent.init()
    _control_agent = agent

    _layout_agent = LayoutAgent(db=db)

    _chroma_watcher = ControlChunk(control_jsonl_path=settings.control_jsonl_path)
    _chroma_watcher.reseed()
    _chroma_watcher.start_watcher()
    search_svc.set_control_chunk(_chroma_watcher)


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


def get_layout_agent() -> LayoutAgent:
    assert _layout_agent is not None, "LayoutAgent not initialized (call init_resources first)"
    return _layout_agent


def get_material_db() -> MaterialDB:
    assert _material_db is not None, "MaterialDB not initialized (call init_resources first)"
    return _material_db
