from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import get_validate_agent
from app.schemas import ApiResponse, ValidateRequest, ValidateResponse, ValidationErrorItem
from model.validate_agent import ValidateAgent

router = APIRouter(prefix="/api/validate", tags=["validate"])

_SCHEMA_CACHE: dict[str, Any] = {}
_SCHEMA_CACHE_LOCK = asyncio.Lock()

_SCHEMA_PATHS = {
    "control": settings.control_schema_path,
    "canvas": settings.schema_path,
    "binding": settings.binding_schema_path,
}


async def _load_schema(category: str) -> dict | None:
    path_str = _SCHEMA_PATHS.get(category)
    if not path_str:
        return None
    global _SCHEMA_CACHE
    if category not in _SCHEMA_CACHE:
        async with _SCHEMA_CACHE_LOCK:
            if category not in _SCHEMA_CACHE:
                schema_path = Path(path_str)
                text = await asyncio.to_thread(
                    lambda: schema_path.read_text(encoding="utf-8")
                )
                _SCHEMA_CACHE[category] = json.loads(text)
    return _SCHEMA_CACHE.get(category)


def _schema_validate(category: str, json_data: dict) -> list[ValidationErrorItem]:
    schema = _SCHEMA_CACHE.get(category)
    if not schema:
        return []
    errors: list[ValidationErrorItem] = []
    for err in jsonschema.Draft7Validator(schema).iter_errors(json_data):
        path = "/".join(str(p) for p in err.absolute_path) if err.absolute_path else ""
        errors.append(ValidationErrorItem(
            path=path,
            message=err.message,
            error_type=err.validator,
        ))
    return errors


def _layout_semantic_validate(json_data: dict) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
    from model.generate_gird import LayoutFile, validate_layout_file
    try:
        layout_file = LayoutFile.model_validate(json_data)
        raw_errors, raw_warnings = validate_layout_file(layout_file)
        errors = [ValidationErrorItem(path=e.path, message=e.message, error_type="semantic") for e in raw_errors]
        warnings = [ValidationErrorItem(path=w, message=w, error_type="warning") for w in raw_warnings]
        return errors, warnings
    except Exception as exc:
        return [ValidationErrorItem(path="layoutIntent", message=str(exc), error_type="parse")], []


@router.post("", response_model=ApiResponse)
async def validate_json(
    req: ValidateRequest,
    agent: ValidateAgent = Depends(get_validate_agent),
):
    all_errors: list[ValidationErrorItem] = []
    all_warnings: list[ValidationErrorItem] = []

    await _load_schema(req.category)

    schema_errors = _schema_validate(req.category, req.json_data)
    all_errors.extend(schema_errors)

    if req.category == "layout":
        sem_errors, sem_warnings = _layout_semantic_validate(req.json_data)
        all_errors.extend(sem_errors)
        all_warnings.extend(sem_warnings)

    ai_result = await agent.validate(req.category, req.json_data)

    for e in ai_result.get("errors", []):
        all_errors.append(ValidationErrorItem(
            path=e.get("path", ""),
            message=e.get("message", ""),
            error_type=e.get("error_type", "ai"),
        ))
    for w in ai_result.get("warnings", []):
        all_warnings.append(ValidationErrorItem(
            path=w.get("path", ""),
            message=w.get("message", ""),
            error_type=w.get("error_type", "warning"),
        ))

    valid = len(all_errors) == 0
    return ApiResponse(data=ValidateResponse(
        valid=valid,
        summary=ai_result.get("summary", ""),
        errors=all_errors,
        warnings=all_warnings,
    ).model_dump())