import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from app.deps import get_canvas_agent
from app.schemas import (
    ApiResponse,
    CanvasLayoutRequest,
    CanvasLayoutResponse,
    LayoutZoneResponse,
    QualityIssueResponse,
    RefineRequest,
    RefineResponse,
)
from model.canva_agent import CanvasAgent, _refine_layout_with_llm

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


@router.post("/layout", response_model=ApiResponse)
async def canvas_layout(
    req: CanvasLayoutRequest,
    agent: CanvasAgent = Depends(get_canvas_agent),
):
    controls = [c.model_dump() for c in req.controls] if req.controls else None
    result = await agent.layout(
        query=req.query,
        controls=controls,
        canvas_width=req.canvas_width,
        canvas_height=req.canvas_height,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_name = f"canvas_{ts}.json"
    output_path = Path(__file__).resolve().parent.parent.parent / "output" / file_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.json_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    issues = [
        QualityIssueResponse(
            severity=i.severity,
            issue_type=i.issue_type,
            message=i.message,
            controls=i.controls,
        )
        for i in result.quality_issues
    ]
    zones = [
        LayoutZoneResponse(
            name=z.name,
            x=z.x,
            y=z.y,
            width=z.width,
            height=z.height,
            controls=z.controls,
        )
        for z in result.skeleton.zones
    ]
    resp = CanvasLayoutResponse(
        json_data=result.json_data,
        content_rect=result.content_rect,
        quality_issues=issues,
        zones=zones,
        missing_controls=result.missing_controls,
        file_name=file_name,
    )
    return ApiResponse(data=resp.model_dump())


@router.post("/refine", response_model=ApiResponse)
async def canvas_refine(req: RefineRequest):
    refined = await _refine_layout_with_llm(req.nodes, req.canvas_width, req.canvas_height)
    resp = RefineResponse(nodes=refined)
    return ApiResponse(data=resp.model_dump())
