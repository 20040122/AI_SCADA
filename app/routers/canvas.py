from fastapi import APIRouter, Depends
from app.schemas import (
    CanvasLayoutRequest,
    CanvasLayoutResponse,
    QualityIssueResponse,
    LayoutZoneResponse,
    RefineRequest,
    RefineResponse,
    ApiResponse,
)
from app.deps import get_canvas_agent
from model.canva_agent import CanvasAgent, _refine_layout_with_llm, _schema_validate

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


@router.post("/layout", response_model=ApiResponse)
def canvas_layout(
    req: CanvasLayoutRequest,
    agent: CanvasAgent = Depends(get_canvas_agent),
):
    controls = [c.model_dump() for c in req.controls]
    result = agent.layout(
        query=req.query,
        controls=controls,
        canvas_width=req.canvas_width,
        canvas_height=req.canvas_height,
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
    )
    return ApiResponse(data=resp.model_dump())


@router.post("/refine", response_model=ApiResponse)
def canvas_refine(req: RefineRequest):
    refined = _refine_layout_with_llm(req.nodes, req.canvas_width, req.canvas_height)
    resp = RefineResponse(nodes=refined)
    return ApiResponse(data=resp.model_dump())