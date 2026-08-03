from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, StrictInt


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
    model_config = ConfigDict(extra="forbid")

    query: str
    title: str
    canvas_width: int = 1920
    canvas_height: int = 1080


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
    missing_controls: list[str] = []
    file_name: str = ""
    pipe_data: Optional[dict[str, Any]] = None


class JsonPatchOperation(BaseModel):
    op: Literal["add", "replace", "remove"]
    path: str
    value: Any = None


class RefineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str
    json_data: dict[str, Any]
    selected_node_i: Optional[StrictInt] = None
    selected_node_ids: Optional[list[StrictInt]] = None


class RefineResponse(BaseModel):
    patch: list[JsonPatchOperation]
    message: str


class UploadCanvasRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str
    json_data: dict[str, Any]


class CorrectionSize(BaseModel):
    width: float
    height: float


class CorrectionItem(BaseModel):
    node_i: int
    display_name: str = ""
    image: str = ""
    before: CorrectionSize
    after: CorrectionSize


class UploadCanvasResponse(BaseModel):
    file_name: str
    json_data: dict[str, Any]
    corrections: list[CorrectionItem] = []
    warnings: list[str] = []


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
    category: Literal["control", "canvas", "layout", "binding"]
    json_data: dict[str, Any]


class ValidationErrorItem(BaseModel):
    path: str = ""
    message: str
    error_type: str = ""


class ValidateResponse(BaseModel):
    valid: bool
    summary: str = ""
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []


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
