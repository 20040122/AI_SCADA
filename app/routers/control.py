from fastapi import APIRouter, Depends
from app.schemas import (
    ControlSearchRequest,
    ControlSearchResponse,
    KeywordResult,
    ControlCandidate,
    ApiResponse,
)
from app.deps import get_control_agent
from model.control_agent import ControlAgent

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/search", response_model=ApiResponse)
def search_control(
    req: ControlSearchRequest,
    agent: ControlAgent = Depends(get_control_agent),
):
    result = agent.process_query(req.query)
    keywords = [
        KeywordResult(
            keyword=kr.keyword,
            count=kr.count,
            candidates=[
                ControlCandidate(
                    displayName=c.displayName,
                    image=c.image,
                    width=c.width,
                    height=c.height,
                    similarity=c.similarity,
                    source=c.source,
                )
                for c in kr.candidates
            ],
        )
        for kr in result.keywords
    ]
    return ApiResponse(
        data=ControlSearchResponse(keywords=keywords, missed=result.missed).model_dump()
    )