from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
import jsonschema

from app.config import settings
from app.schemas import (
    ApiResponse,
    BindingBuildRequest,
    BindingBuildResponse,
    BindingBuildPreview,
    BindingMatchItem,
    BindingMatchRequest,
    BindingMatchResponse,
    BindingNormalizeResponse,
    BindingPreviewResponse,
    BindingProperty,
)
from app.services.binding_config_service import (
    BindingConfigError,
    load_binding_registry,
)
from app.services.build_service import build_bound_json
from app.services.csv_service import (
    CsvError,
    CsvEncodingError,
    CsvTooLargeError,
    CsvTooManyRowsError,
    normalize_csv,
    preview_csv,
)
from app.services.match_service import match_properties

router = APIRouter(prefix="/api/binding", tags=["binding"])

_SCHEMA_CACHE: dict[str, dict] = {}


def _load_schema(path: Path) -> dict:
    key = str(path)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[key]


def _binding_schema_validate(a_data: dict) -> list[str]:
    schema = _load_schema(Path(settings.binding_schema_path))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors({"panel.list": a_data.get("panel.list", [])})]


def _canvas_schema_validate(json_data: dict) -> list[str]:
    schema = _load_schema(Path(settings.schema_path))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(json_data)]


def _registry() -> list[dict[str, Any]]:
    try:
        return load_binding_registry(Path(settings.binding_jsonl_path))
    except BindingConfigError as exc:
        raise HTTPException(
            status_code=422,
            detail="binding.jsonl 配置错误: " + "；".join(exc.errors),
        ) from exc


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
    return ApiResponse(data=BindingPreviewResponse(**result).model_dump())


@router.post("/csv/normalize", response_model=ApiResponse)
async def csv_normalize(
    file: UploadFile = File(...),
    mapping: str = Form(...),
):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="仅接受 .csv 文件")
    try:
        mapping_data = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="mapping 不是合法 JSON") from exc
    if not isinstance(mapping_data, list):
        raise HTTPException(status_code=422, detail="mapping 必须是列表")
    mapping_dict: dict[str, int] = {}
    for item in mapping_data:
        field = item.get("field")
        column = item.get("column")
        if not field or not isinstance(column, int):
            raise HTTPException(status_code=422, detail="mapping 项必须包含 field 与 column")
        mapping_dict[field] = column
    data = await file.read()
    try:
        result = normalize_csv(data, mapping_dict)
    except CsvEncodingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CsvTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CsvTooManyRowsError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CsvError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _fmt(items: list) -> list[str]:
        out: list[str] = []
        for item in items:
            if isinstance(item, dict):
                out.append(f"第 {item['row']} 行: {item['message']}")
            else:
                out.append(str(item))
        return out

    result["errors"] = _fmt(result.get("errors", []))
    result["blocking"] = _fmt(result.get("blocking", []))
    result["properties"] = [
        BindingProperty(**p).model_dump() for p in result.get("properties", [])
    ]
    return ApiResponse(data=BindingNormalizeResponse(**result).model_dump())


@router.post("/match", response_model=ApiResponse)
async def binding_match(req: BindingMatchRequest):
    expectations = _registry()
    result = match_properties(
        req.json_data,
        expectations,
        [p.model_dump() for p in req.properties],
    )
    items = [
        BindingMatchItem(
            panel_node_i=item["panel_node_i"],
            panel_displayName=item["panel_displayName"],
            panel_instance=item["panel_instance"],
            expectation_id=item["expectation_id"],
            expectation_property=item["expectation_property"],
            expectation_required=item["expectation_required"],
            candidates=item["candidates"],
            suggested=item["suggested"],
            confidence=item["confidence"],
            confirmed=item["confirmed"],
        )
        for item in result["items"]
    ]
    return ApiResponse(data=BindingMatchResponse(
        panels=result["panels"],
        expectations=result["expectations"],
        items=items,
    ).model_dump())


@router.post("/build", response_model=ApiResponse)
async def binding_build(req: BindingBuildRequest):
    expectations = _registry()
    assignments = [
        {
            "panel_node_i": a.panel_node_i,
            "expectation_id": a.expectation_id,
            "candidate": a.candidate.model_dump(),
        }
        for a in req.assignments
    ]
    result = build_bound_json(
        req.json_data,
        [p.model_dump() for p in req.properties],
        assignments,
        expectations=expectations,
        canvas_validator=_canvas_schema_validate,
        binding_validator=_binding_schema_validate,
    )
    resp = BindingBuildResponse(
        bound_json=result["bound_json"],
        previews=[
            BindingBuildPreview(**p) for p in result["previews"]
        ],
        errors=result["errors"],
        warnings=result["warnings"],
    )
    return ApiResponse(data=resp.model_dump())
