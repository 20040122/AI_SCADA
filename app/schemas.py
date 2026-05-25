from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class ControlItem(BaseModel):
    displayName: str
    image: str = ""
    width: float = 0
    height: float = 0
    similarity: float = 0.0
    source: str = "vector"


class ControlCandidate(BaseModel):
    displayName: str
    image: str = ""
    width: float = 0
    height: float = 0
    similarity: float = 0.0
    source: str = "vector"


class KeywordResult(BaseModel):
    keyword: str
    count: int = 1
    candidates: list[ControlCandidate] = []


class ControlSearchRequest(BaseModel):
    query: str


class ControlSearchResponse(BaseModel):
    keywords: list[KeywordResult]
    missed: list[str]


class SaveQueryResultRequest(BaseModel):
    query: str
    controls: list[ControlItem]


class CanvasLayoutRequest(BaseModel):
    query: str
    controls: list[ControlItem]
    canvas_width: int = 800
    canvas_height: int = 800


class QualityIssueResponse(BaseModel):
    severity: str
    issue_type: str
    message: str
    controls: list[str]


class LayoutZoneResponse(BaseModel):
    name: str
    x: float
    y: float
    width: float
    height: float
    controls: list[str]


class CanvasLayoutResponse(BaseModel):
    json_data: dict[str, Any]
    content_rect: dict[str, float]
    quality_issues: list[QualityIssueResponse]
    zones: list[LayoutZoneResponse]


class RefineRequest(BaseModel):
    nodes: list[dict[str, Any]]
    canvas_width: int
    canvas_height: int


class RefineResponse(BaseModel):
    nodes: list[dict[str, Any]]


class BindingVariable(BaseModel):
    name: str
    data_type: str = ""
    register_address: str = ""
    description: str = ""


class BindingMatchRequest(BaseModel):
    controls: list[ControlItem]
    variables: list[BindingVariable]


class BindingMatchItem(BaseModel):
    control_name: str
    variable_name: str
    variable_address: str
    confidence: float
    match_reason: str = ""


class BindingConflictItem(BaseModel):
    conflict_type: str
    description: str
    items: list[str]


class BindingMatchResponse(BaseModel):
    matches: list[BindingMatchItem]
    conflicts: list[BindingConflictItem]
    unmatched_controls: list[str]
    unmatched_variables: list[str]


class ValidateRequest(BaseModel):
    json_data: dict[str, Any]


class ValidationErrorItem(BaseModel):
    path: str = ""
    message: str
    error_type: str = ""


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[ValidationErrorItem] = []


class MaterialItem(BaseModel):
    displayName: str
    image: str
    width: float
    height: float
    source: str = "local"
    similarity: float = 0.0


class MaterialListResponse(BaseModel):
    total: int
    items: list[MaterialItem]


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None