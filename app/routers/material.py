from fastapi import APIRouter, Depends
from app.schemas import MaterialItem, MaterialListResponse, ApiResponse, SaveQueryResultRequest
from app.deps import get_material_db
from data.material_db import MaterialDB

router = APIRouter(prefix="/api/material", tags=["material"])


@router.get("/list", response_model=ApiResponse)
def list_materials(db: MaterialDB = Depends(get_material_db)):
    items = [
        MaterialItem(
            displayName=row["displayName"],
            image=row["image"],
            width=row.get("width") or 0,
            height=row.get("height") or 0,
            source=row.get("source", "local"),
        )
        for row in db.list_all()
    ]
    return ApiResponse(data=MaterialListResponse(
        total=len(items), items=items
    ).model_dump())


@router.get("/query-results", response_model=ApiResponse)
def query_results(db: MaterialDB = Depends(get_material_db)):
    rows = db.list_query_results()
    items = [
        MaterialItem(
            displayName=row["displayName"],
            image=row.get("image", ""),
            width=row.get("width") or 0,
            height=row.get("height") or 0,
            source=row.get("source", "query"),
            similarity=row.get("similarity", 0.0),
        )
        for row in rows
    ]
    return ApiResponse(data=MaterialListResponse(
        total=len(items), items=items
    ).model_dump())


@router.delete("/query-results", response_model=ApiResponse)
def clear_query_results(db: MaterialDB = Depends(get_material_db)):
    db.clear_query_results()
    return ApiResponse(data={"cleared": True})


@router.post("/query-results", response_model=ApiResponse)
def save_query_results(
    req: SaveQueryResultRequest,
    db: MaterialDB = Depends(get_material_db),
):
    controls = [c.model_dump() for c in req.controls]
    saved = db.save_query_result(req.query, controls)
    return ApiResponse(data={"saved": saved})