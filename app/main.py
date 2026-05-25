import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import control, canvas, binding, validate, material
from app.deps import get_material_db, get_control_agent

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


@app.on_event("startup")
def startup():
    get_material_db()
    get_control_agent()