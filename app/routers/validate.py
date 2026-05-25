import json
from pathlib import Path
from fastapi import APIRouter
from app.schemas import ValidateRequest, ValidateResponse, ValidationErrorItem, ApiResponse
from app.config import settings

router = APIRouter(prefix="/api/validate", tags=["validate"])

_schema_cache = None


def _load_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        schema_path = Path(settings.schema_path)
        _schema_cache = json.loads(schema_path.read_text(encoding="utf-8"))
    return _schema_cache


@router.post("", response_model=ApiResponse)
def validate_json(req: ValidateRequest):
    import jsonschema

    schema = _load_schema()
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