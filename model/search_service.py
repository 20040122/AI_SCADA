from data.chroma import ControlChunk

_chunk = ControlChunk()

SIMILARITY_THRESHOLD = 0.55


def search_controls(keywords: list[str], n_results: int = 5) -> dict[str, dict]:
    results: dict[str, dict] = {}

    for keyword in keywords:
        hits = _chunk.query(keyword, n_results=n_results)
        results[keyword] = {
            "id": hits["ids"][0][0],
            "document": hits["documents"][0][0],
            "metadata": hits["metadatas"][0][0],
            "distance": hits["distances"][0][0],
        }

    return results


def search_controls_with_threshold(
    keywords: list[str], n_results: int = 5
) -> dict[str, dict]:
    results: dict[str, dict] = {}

    for keyword in keywords:
        hits = _chunk.query(keyword, n_results=n_results)
        distance = hits["distances"][0][0]
        similarity = 1 - distance
        matched = similarity >= SIMILARITY_THRESHOLD
        results[keyword] = {
            "id": hits["ids"][0][0],
            "document": hits["documents"][0][0],
            "metadata": hits["metadatas"][0][0],
            "distance": distance,
            "similarity": round(similarity, 4),
            "matched": matched,
        }

    return results