from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_control_agent
from app.schemas import (
    ApiResponse,
    ControlCandidate,
    ControlSearchRequest,
    ControlSearchResponse,
    KeywordResult,
)
from model.control_agent import ControlAgent
from model.control_tools.catalog import CatalogCorruptError
from model.control_tools.extract import (
    ControlModelOutputError,
    ControlModelTimeoutError,
    ControlModelUnavailableError,
)

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/search", response_model=ApiResponse)
async def search_control(
    req: ControlSearchRequest,
    agent: ControlAgent = Depends(get_control_agent),
):
    try:
        result = await agent.process_query(req.query)
    except ControlModelOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ControlModelUnavailableError, CatalogCorruptError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ControlModelTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    keywords = [
        KeywordResult(
            keyword=kr.keyword,
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
            canGenerate=kr.canGenerate,
        )
        for kr in result.keywords
    ]
    return ApiResponse(
        data=ControlSearchResponse(keywords=keywords, missed=result.missed).model_dump()
    )
