from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.deps import get_binding_agent
from app.schemas import (
    ApiResponse,
    BindingBuildPreview,
    BindingBuildRequest,
    BindingBuildResponse,
    BindingMatchRequest,
    BindingMatchResponse,
    BindingPreviewResponse,
    BindingRequestRow,
)
from app.services.csv_service import (
    CsvError,
    CsvEncodingError,
    CsvTooLargeError,
    CsvTooManyRowsError,
    preview_csv,
)
from model.binding_agent import BindingAgent

router = APIRouter(prefix="/api/binding", tags=["binding"])


@router.post("/csv/preview", response_model=ApiResponse)
async def csv_preview(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="仅接受 .csv 文件")
    data = await file.read()
    try:
        result = preview_csv(data)
    except CsvEncodingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CsvTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CsvTooManyRowsError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CsvError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    requests = [BindingRequestRow(**r) for r in result["requests"]]
    return ApiResponse(data=BindingPreviewResponse(
        encoding=result["encoding"],
        total_rows=result["total_rows"],
        requests=requests,
    ).model_dump())


@router.post("/match", response_model=ApiResponse)
async def binding_match(
    req: BindingMatchRequest,
    agent: BindingAgent = Depends(get_binding_agent),
):
    result = agent.match(
        req.json_data,
        [r.model_dump() for r in req.requests],
    )
    return ApiResponse(data=BindingMatchResponse(**result).model_dump())


@router.post("/build", response_model=ApiResponse)
async def binding_build(
    req: BindingBuildRequest,
    agent: BindingAgent = Depends(get_binding_agent),
):
    result = agent.build(
        req.json_data,
        [r.model_dump() for r in req.requests],
        [a.model_dump() for a in req.assignments],
    )
    resp = BindingBuildResponse(
        bound_json=result["bound_json"],
        previews=[BindingBuildPreview(**p) for p in result["previews"]],
        errors=result["errors"],
        warnings=result["warnings"],
    )
    return ApiResponse(data=resp.model_dump())
