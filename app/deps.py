from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings
from data.chroma import ControlChunk
from data.sqlite.material_db import MaterialDB
from model.binding_agent import BindingAgent
from model.control_tools import search_service as search_svc
from model.control_agent import ControlAgent
from model.layout_agent import LayoutAgent
from model.refine_agent import RefineAgent
from model.validate_agent import ValidateAgent

_control_agent: Optional[ControlAgent] = None
_layout_agent: Optional[LayoutAgent] = None
_refine_agent: Optional[RefineAgent] = None
_validate_agent: Optional[ValidateAgent] = None
_binding_agent: Optional[BindingAgent] = None
_material_db: Optional[MaterialDB] = None
_chroma_watcher: Optional[ControlChunk] = None


async def init_resources() -> None:
    global _material_db, _control_agent, _layout_agent, _refine_agent, _validate_agent, _binding_agent, _chroma_watcher

    db = MaterialDB()
    await db.init_db()
    _material_db = db

    agent = ControlAgent(db=db)
    await agent.init()
    _control_agent = agent

    _layout_agent = LayoutAgent(db=db)
    _refine_agent = RefineAgent()
    _validate_agent = ValidateAgent()
    _binding_agent = BindingAgent(registry_path=Path(settings.binding_jsonl_path))

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


def get_refine_agent() -> RefineAgent:
    assert _refine_agent is not None, "RefineAgent not initialized (call init_resources first)"
    return _refine_agent


def get_validate_agent() -> ValidateAgent:
    assert _validate_agent is not None, "ValidateAgent not initialized (call init_resources first)"
    return _validate_agent


def get_binding_agent() -> BindingAgent:
    assert _binding_agent is not None, "BindingAgent not initialized (call init_resources first)"
    return _binding_agent


def get_material_db() -> MaterialDB:
    assert _material_db is not None, "MaterialDB not initialized (call init_resources first)"
    return _material_db
