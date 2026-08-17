from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.generation_service import (
    AssetUploader,
    GenerationManager,
    make_default_generator,
)
from data.sqlite.material_db import MaterialDB
from model.binding_agent import BindingAgent
from model.control_agent import ControlAgent
from model.control_tools.catalog import ControlCatalogManager
from model.layout_agent import LayoutAgent
from model.refine_agent import RefineAgent
from model.validate_agent import ValidateAgent

_control_agent: Optional[ControlAgent] = None
_control_catalog: Optional[ControlCatalogManager] = None
_layout_agent: Optional[LayoutAgent] = None
_refine_agent: Optional[RefineAgent] = None
_validate_agent: Optional[ValidateAgent] = None
_binding_agent: Optional[BindingAgent] = None
_material_db: Optional[MaterialDB] = None
_generation_manager: Optional[GenerationManager] = None


async def init_resources() -> None:
    global _material_db, _control_agent, _control_catalog, _layout_agent, _refine_agent, _validate_agent, _binding_agent, _generation_manager

    db = MaterialDB()
    await db.init_db()
    _material_db = db

    manager = ControlCatalogManager(
        chroma_dir=settings.chroma_dir,
        control_jsonl_path=settings.control_jsonl_path,
        mappings_path=settings.control_mappings_path,
    )
    agent = ControlAgent(manager=manager)
    await agent.init()
    _control_agent = agent
    _control_catalog = manager

    generation_manager = GenerationManager(
        temp_dir=Path(settings.generation_temp_dir),
        ttl_seconds=settings.generation_ttl_seconds,
        generator=make_default_generator(
            Path(settings.qwen_reference_path), settings.qwen_timeout
        ),
        uploader=AssetUploader(
            base_url=settings.daoscada_upload_url,
            timeout=settings.daoscada_upload_timeout,
        ),
        jsonl_path=Path(settings.control_jsonl_path),
        catalog=manager,
        db=db,
    )
    generation_manager.start()
    _generation_manager = generation_manager

    _layout_agent = LayoutAgent(db=db)
    _refine_agent = RefineAgent()
    _validate_agent = ValidateAgent()
    _binding_agent = BindingAgent(registry_path=Path(settings.binding_jsonl_path))


async def close_resources() -> None:
    global _material_db, _control_catalog, _generation_manager
    if _generation_manager is not None:
        await _generation_manager.stop()
        _generation_manager = None
    if _control_catalog is not None:
        _control_catalog.close()
        _control_catalog = None
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


def get_generation_manager() -> GenerationManager:
    assert _generation_manager is not None, "GenerationManager not initialized (call init_resources first)"
    return _generation_manager
