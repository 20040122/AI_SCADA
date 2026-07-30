from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.deps import close_resources, init_resources
from app.routers import binding, canvas, control, material, validate


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_resources()
    yield
    await close_resources()


app = FastAPI(
    title="SCADA AI Plugin",
    description="DaoSCADA AI智能组态插件",
    version="1.0.0",
    lifespan=lifespan,
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
