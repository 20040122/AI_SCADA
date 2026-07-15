from fastapi import APIRouter, Depends

from app.deps import get_material_db
from app.schemas import ApiResponse, MaterialItem, MaterialListResponse, SaveQueryResultRequest
from app.services.material_service import MaterialService
from data.sqlite.material_db import MaterialDB

router = APIRouter(prefix="/api/material", tags=["material"])


@router.get("/list", response_model=ApiResponse)
async def list_materials(db: MaterialDB = Depends(get_material_db)):
    service = MaterialService(db)
    items = await service.list_controls()
    return ApiResponse(data=MaterialListResponse(
        total=len(items), items=[MaterialItem(**i) for i in items]
    ).model_dump())


@router.get("/query-results", response_model=ApiResponse)
async def query_results(db: MaterialDB = Depends(get_material_db)):
    service = MaterialService(db)
    items = await service.list_query_results()
    return ApiResponse(data=MaterialListResponse(
        total=len(items), items=[MaterialItem(**i) for i in items]
    ).model_dump())


@router.delete("/query-results", response_model=ApiResponse)
async def clear_query_results(db: MaterialDB = Depends(get_material_db)):
    service = MaterialService(db)
    await service.clear_query_results()
    return ApiResponse(data={"cleared": True})


@router.post("/query-results", response_model=ApiResponse)
async def save_query_results(
    req: SaveQueryResultRequest,
    db: MaterialDB = Depends(get_material_db),
):
    service = MaterialService(db)
    controls = [c.model_dump() for c in req.controls]
    saved = await service.save_query_result(req.query, controls)
    return ApiResponse(data={"saved": saved})
