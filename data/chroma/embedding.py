from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

MODEL_NAME = "BAAI/bge-small-zh-v1.5"

_ef = None


def get_embedding_function() -> SentenceTransformerEmbeddingFunction:
    global _ef
    if _ef is None:
        _ef = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
    return _ef