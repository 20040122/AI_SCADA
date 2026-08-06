from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BGE_MODEL_PATH = REPO_ROOT / "model" / "bge-small-zh-v1.5"

_similarity = None


class BgeSimilarity:
    def __init__(self, model_path: Path = BGE_MODEL_PATH):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(str(model_path), local_files_only=True)
        self._model.eval()

    def similarity(self, a: str, b: str) -> float:
        import numpy as np

        va = self._model.encode([a], normalize_embeddings=True)[0]
        vb = self._model.encode([b], normalize_embeddings=True)[0]
        return float(np.dot(va, vb))


def get_similarity() -> BgeSimilarity:
    global _similarity
    if _similarity is None:
        _similarity = BgeSimilarity()
    return _similarity
