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
    pipe_data: Optional[dict[str, Any]] = None


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


class BindingProperty(BaseModel):
    projectId: str
    projectName: str
    deviceId: str
    deviceName: str
    propertyId: str
    propertyName: str
    dataType: str
    writable: bool
    unit: str = ""
    dataTypeDesc: str = ""


class BindingColumnSuggestion(BaseModel):
    field: str
    column: Any
    source: str = "exact"


class BindingColumnAmbiguity(BaseModel):
    column: Any = None
    header: str = ""
    matched_fields: list[str] = []
    detail: str = ""


class BindingMapping(BaseModel):
    suggestions: list[BindingColumnSuggestion]
    ambiguities: list[BindingColumnAmbiguity]
    missing: list[str]


class BindingPreviewResponse(BaseModel):
    encoding: str
    headers: list[str]
    total_rows: int
    rows: list[list[str]]
    mapping: BindingMapping


class BindingNormalizeResponse(BaseModel):
    properties: list[BindingProperty]
    errors: list[str]
    blocked: bool = False
    blocking: list[str] = []


class BindingCandidate(BaseModel):
    projectId: str
    projectName: str
    deviceId: str
    deviceName: str
    propertyId: str
    propertyName: str
    dataType: str
    writable: bool
    unit: str = ""
    dataTypeDesc: str = ""
    device_name_similarity: float = 0.0
    property_name_similarity: float = 0.0
    score: float = 0.0
    lead: float = 0.0
    confidence: str = "none"
    evidence: list[str] = []
    key: str = ""


class BindingMatchItem(BaseModel):
    panel_node_i: int
    panel_displayName: str
    panel_instance: int
    expectation_id: str
    expectation_property: str
    expectation_required: bool
    candidates: list[BindingCandidate]
    suggested: Optional[str] = None
    confidence: str = "none"
    confirmed: bool = False


class BindingMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_data: dict[str, Any]
    properties: list[BindingProperty]


class BindingMatchResponse(BaseModel):
    panels: list[dict[str, Any]]
    expectations: list[dict[str, Any]]
    items: list[BindingMatchItem]


class BindingAssignment(BaseModel):
    panel_node_i: int
    expectation_id: str
    candidate: BindingProperty


class BindingBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_data: dict[str, Any]
    properties: list[BindingProperty]
    assignments: list[BindingAssignment]


class BindingBuildPreview(BaseModel):
    node_i: int
    displayName: str
    instance: int
    panel_list: list[dict[str, Any]]
    has_existing: bool = False


class BindingBuildResponse(BaseModel):
    bound_json: Optional[dict[str, Any]] = None
    previews: list[BindingBuildPreview]
    errors: list[str] = []
    warnings: list[str] = []


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
