import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.deps import get_layout_agent, get_material_db, get_refine_agent
from app.schemas import (
    ApiResponse,
    CanvasLayoutRequest,
    CanvasLayoutResponse,
    RefineRequest,
    RefineResponse,
    CorrectionItem,
    UploadCanvasRequest,
    UploadCanvasResponse,
)
from app.services.canvas_upload_service import (
    CanvasUploadService,
    UploadBlockedError,
    UploadTimeoutError,
    UploadUpstreamError,
)
from data.sqlite.material_db import MaterialDB
from model.layout_agent import LayoutAgent
from model.layout_agent import LayoutOutputError
from model.layout_tools.compute_position import MissingMaterialError
from model.layout_tools.get_intent import IntentModelOutputError, IntentModelTimeoutError, IntentModelUnavailableError, StructuredPromptError, image_to_structured_prompt
from model.layout_tools.get_connection import ConnectionModelError as PipingModelError
from model.layout_tools.get_connection import ConnectionModelTimeoutError as PipingModelTimeoutError
from model.layout_tools.get_connection import ConnectionModelUnavailableError as PipingModelUnavailableError
from model.layout_tools.get_connection import ConnectionValidationError as PipingValidationError
from model.layout_tools.get_connection import TopologyMismatchError
from model.layout_tools.get_connection import PipingSectionError
from model.layout_tools.pipe_serializer import PipeConversionError, PipeTemplateError
from model.refine_agent import (
    RefineAgent,
    RefineInputError,
    RefineModelError,
    RefineUnavailableError,
)

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


async def _generate_layout(
    agent: LayoutAgent,
    query: str,
    width: int,
    height: int,
    title: str,
    skip_structure_count: bool = False,
):
    try:
        return await agent.generate(
            query=query,
            width=width,
            height=height,
            title=title,
            skip_structure_count=skip_structure_count,
        )
    except MissingMaterialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LayoutOutputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StructuredPromptError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [
                    {"path": item.path, "message": item.message}
                    for item in exc.errors
                ]
            },
        ) from exc
    except (PipingValidationError, TopologyMismatchError, PipingSectionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (PipeConversionError, PipeTemplateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntentModelOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PipingModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PipingModelTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except PipingModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except IntentModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntentModelTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


def _persist_and_respond(result, title: str) -> ApiResponse:
    safe = re.sub(r'[\\/:*?"<>|]', "_", title.strip() or "测试系统")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_name = f"{safe}_{ts}.json"
    output_path = Path(__file__).resolve().parent.parent.parent / "output" / file_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.json_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    resp = CanvasLayoutResponse(
        json_data=result.json_data,
        content_rect=result.content_rect,
        quality_issues=[],
        zones=[],
        missing_controls=[],
        file_name=file_name,
        pipe_data=result.pipe_data,
    )
    return ApiResponse(data=resp.model_dump())


@router.post("/layout", response_model=ApiResponse)
async def canvas_layout(
    req: CanvasLayoutRequest,
    agent: LayoutAgent = Depends(get_layout_agent),
):
    result = await _generate_layout(
        agent,
        query=req.query,
        width=req.canvas_width,
        height=req.canvas_height,
        title=req.title.strip(),
    )
    return _persist_and_respond(result, req.title)


@router.post("/layout/image", response_model=ApiResponse)
async def canvas_layout_image(
    file: UploadFile = File(...),
    title: str = Form(""),
    canvas_width: int = Form(1920),
    canvas_height: int = Form(1080),
    agent: LayoutAgent = Depends(get_layout_agent),
    db: MaterialDB = Depends(get_material_db),
):
    materials = await db.list_query_results("")
    if not materials:
        raise HTTPException(status_code=422, detail="query_results 表为空")

    image = await file.read()
    try:
        prompt = await image_to_structured_prompt(image, materials)
    except StructuredPromptError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [
                    {"path": item.path, "message": item.message}
                    for item in exc.errors
                ]
            },
        ) from exc
    except IntentModelOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except IntentModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = await _generate_layout(
        agent,
        query=prompt,
        width=canvas_width,
        height=canvas_height,
        title=title.strip(),
        skip_structure_count=True,
    )
    return _persist_and_respond(result, title)


@router.post("/refine", response_model=ApiResponse)
async def canvas_refine(
    req: RefineRequest,
    agent: RefineAgent = Depends(get_refine_agent),
):
    try:
        if req.selected_node_i is not None and req.selected_node_ids is not None:
            raise HTTPException(
                status_code=422,
                detail="selected_node_i and selected_node_ids are mutually exclusive",
            )
        if req.selected_node_ids is not None:
            if not req.selected_node_ids:
                raise HTTPException(
                    status_code=422, detail="selected_node_ids must not be empty"
                )
            if len(set(req.selected_node_ids)) != len(req.selected_node_ids):
                raise HTTPException(
                    status_code=422, detail="selected_node_ids must be unique"
                )

        result = await agent.refine(
            req.instruction,
            req.json_data,
            req.selected_node_i,
            req.selected_node_ids,
        )
    except RefineInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RefineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RefineModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    resp = RefineResponse(patch=result.patch, message=result.message)
    return ApiResponse(data=resp.model_dump(exclude_none=True))


@router.post("/upload", response_model=ApiResponse)
async def canvas_upload(
    req: UploadCanvasRequest,
    db: MaterialDB = Depends(get_material_db),
):
    service = CanvasUploadService()
    try:
        library = await db.list_all()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"material library unavailable: {exc}") from exc
    try:
        result = await service.upload_canvas(req.file_name, req.json_data, library, pipe_data=req.pipe_data)
    except UploadBlockedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (PipeConversionError, PipeTemplateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UploadTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except UploadUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    resp = UploadCanvasResponse(
        file_name=req.file_name,
        json_data=result.json_data,
        corrections=[CorrectionItem(**item) for item in result.corrections],
        warnings=result.warnings,
    )
    return ApiResponse(data=resp.model_dump())
