from __future__ import annotations

from fastapi import APIRouter

from app.schemas import (
    ApiResponse,
    BindingConflictItem,
    BindingMatchItem,
    BindingMatchRequest,
    BindingMatchResponse,
)
from app.services.binding_service import match_variables

router = APIRouter(prefix="/api/binding", tags=["binding"])


@router.post("/match", response_model=ApiResponse)
async def binding_match(req: BindingMatchRequest):
    controls = [{"displayName": c.displayName} for c in req.controls]
    variables = [
        {"name": v.name, "register_address": v.register_address}
        for v in req.variables
    ]

    matches, conflicts, unmatched_controls, unmatched_variables = match_variables(
        controls, variables, threshold=0.5
    )

    match_items = [
        BindingMatchItem(
            control_name=m["control_name"],
            variable_name=m["variable_name"],
            variable_address=m["variable_address"],
            confidence=m["confidence"],
            match_reason=m["match_reason"],
        )
        for m in matches
    ]
    conflict_items = [
        BindingConflictItem(
            conflict_type=c["conflict_type"],
            description=c["description"],
            items=c["items"],
        )
        for c in conflicts
    ]

    return ApiResponse(data=BindingMatchResponse(
        matches=match_items,
        conflicts=conflict_items,
        unmatched_controls=unmatched_controls,
        unmatched_variables=unmatched_variables,
    ).model_dump())
