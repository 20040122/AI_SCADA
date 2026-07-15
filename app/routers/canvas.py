import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_layout_agent, get_refine_agent
from app.schemas import (
    ApiResponse,
    CanvasLayoutRequest,
    CanvasLayoutResponse,
    RefineRequest,
    RefineResponse,
)
from model.layout_agent import LayoutAgent
from model.refine_agent import (
    RefineAgent,
    RefineInputError,
    RefineModelError,
    RefineUnavailableError,
)

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


@router.post("/layout", response_model=ApiResponse)
async def canvas_layout(
    req: CanvasLayoutRequest,
    agent: LayoutAgent = Depends(get_layout_agent),
):
    controls = [c.model_dump() for c in req.controls] if req.controls else None
    result = await agent.generate(
        query=req.query,
        width=req.canvas_width,
        height=req.canvas_height,
        title=req.title.strip(),
        controls=controls,
    )

    safe = re.sub(r'[\\/:*?"<>|]', "_", req.title.strip())
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
    )
    return ApiResponse(data=resp.model_dump())


@router.post("/refine", response_model=ApiResponse)
async def canvas_refine(
    req: RefineRequest,
    agent: RefineAgent = Depends(get_refine_agent),
):
    try:
        result = await agent.refine(
            req.instruction,
            req.json_data,
            req.selected_node_i,
        )
    except RefineInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RefineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RefineModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    resp = RefineResponse(patch=result.patch, message=result.message)
    return ApiResponse(data=resp.model_dump(exclude_none=True))
