from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.deps import get_validate_agent
from app.schemas import ApiResponse, RulesResponse, ValidateRequest, ValidateResponse, ValidationErrorItem
from app.services.validation_service import ValidationService
from model.validate_agent import ValidateAgent

router = APIRouter(prefix="/api/validate", tags=["validate"])


@router.post("", response_model=ApiResponse)
async def validate_json(
    req: ValidateRequest,
    agent: ValidateAgent = Depends(get_validate_agent),
):
    service = ValidationService.instance()
    errors, warnings = service.validate(req.category, req.json_data)

    if not errors:
        ai_result = await agent.validate(req.category, req.json_data)
        for item in ai_result.get("errors", []):
            warnings.append(_as_ai_warning(item))
        for item in ai_result.get("warnings", []):
            warnings.append(_as_ai_warning(item))

    valid = len(errors) == 0
    summary = _make_summary(valid, errors, warnings)
    return ApiResponse(data=ValidateResponse(
        valid=valid,
        summary=summary,
        errors=errors,
        warnings=warnings,
    ).model_dump())


@router.get("/rules", response_model=ApiResponse)
async def validate_rules():
    service = ValidationService.instance()
    response = RulesResponse(categories=service.rules_meta())
    return ApiResponse(data=response.model_dump())


def _as_ai_warning(item: dict[str, Any]) -> ValidationErrorItem:
    return ValidationErrorItem(
        path=item.get("path", ""),
        message=item.get("message", ""),
        error_type=item.get("error_type", "ai"),
        source="ai",
    )


def _make_summary(valid: bool, errors: list[ValidationErrorItem], warnings: list[ValidationErrorItem]) -> str:
    if not valid:
        return f"校验未通过：{len(errors)} 个错误，{len(warnings)} 个警告"
    if warnings:
        return f"校验通过：{len(warnings)} 个警告"
    return "校验通过"
