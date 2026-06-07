import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import control, canvas, binding, validate, material
from app.deps import get_material_db, get_control_agent
from data.chroma import ControlChunk

app = FastAPI(
    title="SCADA AI Plugin",
    description="DaoSCADA AI智能组态插件",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(control.router)
app.include_router(canvas.router)
app.include_router(binding.router)
app.include_router(validate.router)
app.include_router(material.router)

_chroma_watcher: Optional[ControlChunk] = None


@app.on_event("startup")
def startup():
    global _chroma_watcher

    get_material_db()
    get_control_agent()

    _chroma_watcher = ControlChunk(control_jsonl_path=settings.control_jsonl_path)
    _chroma_watcher.check_and_reseed()
    _chroma_watcher.start_watcher()


@app.on_event("shutdown")
def shutdown():
    global _chroma_watcher
    if _chroma_watcher is not None:
        _chroma_watcher.stop_watcher()