from data.chroma import ControlChunk
_chunk = ControlChunk()
SIMILARITY_THRESHOLD = 0.55


def search_controls_with_threshold(
    keywords: list[str], n_results: int = 5
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}

    for keyword in keywords:
        hits = _chunk.query(keyword, n_results=n_results)
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