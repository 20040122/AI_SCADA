from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
from fastapi import APIRouter

from app.config import settings
from app.schemas import ApiResponse, ValidateRequest, ValidateResponse, ValidationErrorItem

router = APIRouter(prefix="/api/validate", tags=["validate"])

_schema_cache = None
_schema_cache_lock = asyncio.Lock()


async def _load_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        async with _schema_cache_lock:
            if _schema_cache is None:
                schema_path = Path(settings.schema_path)
                text = await asyncio.to_thread(
                    lambda: schema_path.read_text(encoding="utf-8")
                )
                _schema_cache = json.loads(text)
    return _schema_cache


@router.post("", response_model=ApiResponse)
async def validate_json(req: ValidateRequest):
    schema = await _load_schema()
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(req.json_data))

    if not errors:
        return ApiResponse(data=ValidateResponse(valid=True).model_dump())

    error_items = []
    for err in errors:
        path = "/".join(str(p) for p in err.absolute_path) if err.absolute_path else ""
        error_items.append(ValidationErrorItem(
            path=path,
            message=err.message,
            error_type=err.validator,
        ))

    return ApiResponse(data=ValidateResponse(
        valid=False, errors=error_items
    ).model_dump())
