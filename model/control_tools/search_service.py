from __future__ import annotations

import asyncio
from typing import Optional

from data.chroma import ControlChunk

_chunk: Optional[ControlChunk] = None
SIMILARITY_THRESHOLD = 0.55


def set_control_chunk(chunk: ControlChunk) -> None:
    global _chunk
    _chunk = chunk


async def search_controls_with_threshold(
    keywords: list[str], n_results: int = 5
) -> dict[str, list[dict]]:
    global _chunk
    if _chunk is None:
        _chunk = ControlChunk()
    _chunk.check_and_reseed()

    results: dict[str, list[dict]] = {}

    for keyword in keywords:
        hits = await asyncio.to_thread(_chunk.query, keyword, n_results)
        candidates = []
        for i in range(len(hits["ids"][0])):
            distance = hits["distances"][0][i]
            similarity = round(1 - distance, 4)
            matched = similarity >= SIMILARITY_THRESHOLD
            candidates.append({
                "id": hits["ids"][0][i],
                "document": hits["documents"][0][i],
                "metadata": hits["metadatas"][0][i],
                "distance": distance,
                "similarity": similarity,
                "matched": matched,
                "source": "vector",
            })
        results[keyword] = candidates

    return results
