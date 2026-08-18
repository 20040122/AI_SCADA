from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.deps import get_generation_manager
from app.schemas import ApiResponse, GenerationCreateRequest, GenerationStatusResponse
from app.services.generation_service import GenerationAPIError, GenerationManager

router = APIRouter(prefix="/api/control/generations", tags=["control-generations"])


@router.post("", status_code=202, response_model=ApiResponse)
async def create_generation(
    req: GenerationCreateRequest,
    manager: GenerationManager = Depends(get_generation_manager),
):
    try:
        task = manager.create(req.query, req.name)
    except GenerationAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ApiResponse(
        data={"generation_id": task.generation_id, "status": task.status}
    )


@router.get("/{generation_id}", response_model=ApiResponse)
async def get_generation(
    generation_id: str,
    manager: GenerationManager = Depends(get_generation_manager),
):
    task = manager.get(generation_id)
    if task is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    return ApiResponse(
        data=GenerationStatusResponse(**manager.to_dict(task)).model_dump()
    )


@router.get("/{generation_id}/preview")
async def get_preview(
    generation_id: str,
    manager: GenerationManager = Depends(get_generation_manager),
):
    try:
        path = manager.get_preview_path(generation_id)
    except GenerationAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png")


@router.post("/{generation_id}/regenerate", response_model=ApiResponse)
async def regenerate_generation(
    generation_id: str,
    manager: GenerationManager = Depends(get_generation_manager),
):
    try:
        task = manager.regenerate(generation_id)
    except GenerationAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ApiResponse(
        data={"generation_id": task.generation_id, "status": task.status}
    )


@router.post("/{generation_id}/confirm", response_model=ApiResponse)
async def confirm_generation(
    generation_id: str,
    manager: GenerationManager = Depends(get_generation_manager),
):
    try:
        record = await manager.confirm(generation_id)
    except GenerationAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ApiResponse(data=record)


@router.delete("/{generation_id}", response_model=ApiResponse)
async def discard_generation(
    generation_id: str,
    manager: GenerationManager = Depends(get_generation_manager),
):
    try:
        manager.discard(generation_id)
    except GenerationAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ApiResponse(data=None)
