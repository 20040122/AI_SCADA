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
    canGenerate: bool = False


class ControlSearchRequest(BaseModel):
    query: str


class ControlSearchResponse(BaseModel):
    keywords: list[KeywordResult]
    missed: list[str]


class GenerationCreateRequest(BaseModel):
    query: str
    name: str


class GenerationCreateResponse(BaseModel):
    generation_id: str
    status: str


class GenerationStatusResponse(BaseModel):
    generation_id: str
    name: str
    status: str
    seed: int
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    preview_url: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


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


class BindingRequestRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_number: int
    displayName: str
    propertyName: str


class BindingPreviewResponse(BaseModel):
    encoding: str
    total_rows: int
    requests: list[BindingRequestRow]


class BindingCandidate(BaseModel):
    binding_id: str
    propertyName: str
    projectName: str
    deviceName: str
    dataType: str
    writable: bool
    unit: str = ""
    score: float = 0.0
    evidence: list[str] = []


class BindingTarget(BaseModel):
    node_i: int
    node_id: Any = None
    displayName: str
    handler: str
    existing: Any = None


class BindingMatchItem(BaseModel):
    row_number: int
    target_node_i: Optional[int] = None
    requested_displayName: str
    requested_propertyName: str
    candidates: list[BindingCandidate] = []
    suggested_binding_id: Optional[str] = None
    lead: float = 0.0
    confidence: str = "none"


class BindingMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_data: dict[str, Any]
    requests: list[BindingRequestRow]


class BindingMatchResponse(BaseModel):
    targets: list[BindingTarget]
    items: list[BindingMatchItem]
    blocked: bool = False
    errors: list[str] = []


class BindingAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_number: int
    binding_id: str


class BindingBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_data: dict[str, Any]
    requests: list[BindingRequestRow]
    assignments: list[BindingAssignment]


class BindingBuildPreview(BaseModel):
    node_i: int
    displayName: str
    handler: str
    before: Any = None
    after: list[dict[str, Any]] = []


class BindingBuildResponse(BaseModel):
    bound_json: Optional[dict[str, Any]] = None
    previews: list[BindingBuildPreview] = []
    errors: list[str] = []
    warnings: list[str] = []
    applied_count: int = 0
    skipped_count: int = 0


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
