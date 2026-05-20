from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pathlib import Path

MODEL_NAME = str(Path(__file__).resolve().parents[2] / "model" / "bge-small-zh-v1.5")

_ef = None


def get_embedding_function() -> SentenceTransformerEmbeddingFunction:
    global _ef
    if _ef is None:
        _ef = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
    return _ef
