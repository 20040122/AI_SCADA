from __future__ import annotations
import re
from fastapi import APIRouter
from app.schemas import (
    BindingMatchRequest,
    BindingMatchResponse,
    BindingMatchItem,
    BindingConflictItem,
    ApiResponse,
)
from model.search_service import search_controls_with_threshold

router = APIRouter(prefix="/api/binding", tags=["binding"])


def _normalize(name: str) -> str:
    return re.sub(r"[_\s\-]+", "", name).lower()


def _fuzzy_match(control_name: str, variable_name: str) -> float:
    cn = _normalize(control_name)
    vn = _normalize(variable_name)
    if cn == vn:
        return 1.0
    if cn in vn or vn in cn:
        return 0.85
    common = sum(1 for c in cn if c in vn)
    if not cn:
        return 0.0
    return common / len(cn) * 0.6


@router.post("/match", response_model=ApiResponse)
def binding_match(req: BindingMatchRequest):
    matches: list[BindingMatchItem] = []
    conflicts: list[BindingConflictItem] = []
    matched_controls: set[str] = set()
    matched_variables: set[str] = set()
    address_map: dict[str, list[str]] = {}

    for ctrl in req.controls:
        best_var = None
        best_score = 0.0
        best_reason = ""
        for var in req.variables:
            score = _fuzzy_match(ctrl.displayName, var.name)
            if score > best_score:
                best_score = score
                best_var = var
                best_reason = (
                    "exact" if score >= 0.99
                    else "contains" if score >= 0.8
                    else "partial"
                )
        if best_var and best_score >= 0.5:
            matches.append(BindingMatchItem(
                control_name=ctrl.displayName,
                variable_name=best_var.name,
                variable_address=best_var.register_address,
                confidence=round(best_score, 4),
                match_reason=best_reason,
            ))
            matched_controls.add(ctrl.displayName)
            matched_variables.add(best_var.name)
            if best_var.register_address:
                address_map.setdefault(best_var.register_address, []).append(
                    f"{ctrl.displayName}->{best_var.name}"
                )

    for addr, items in address_map.items():
        if len(items) > 1:
            conflicts.append(BindingConflictItem(
                conflict_type="duplicate_address",
                description=f"寄存器地址 {addr} 被多个控件绑定",
                items=items,
            ))

    seen_var_names: dict[str, str] = {}
    for var in req.variables:
        if var.name in seen_var_names:
            conflicts.append(BindingConflictItem(
                conflict_type="duplicate_variable",
                description=f"变量名 {var.name} 重复",
                items=[seen_var_names[var.name], var.name],
            ))
        seen_var_names[var.name] = var.name

    return ApiResponse(data=BindingMatchResponse(
        matches=matches,
        conflicts=conflicts,
        unmatched_controls=[c.displayName for c in req.controls if c.displayName not in matched_controls],
        unmatched_variables=[v.name for v in req.variables if v.name not in matched_variables],
    ).model_dump())