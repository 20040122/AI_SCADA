from data.chroma import ControlChunk

_chunk = ControlChunk()


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