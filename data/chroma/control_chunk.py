import json
from pathlib import Path
from typing import Optional

import chromadb

from data.chroma.embedding import get_embedding_function

CONTROL_JSONL = Path(__file__).resolve().parent.parent / "control.jsonl"

COLLECTION_NAME = "control_chunks"

DOCUMENT_TEMPLATE = (
    "SCADA 控件：{displayName}，宽度 {width}，高度 {height}，资源路径 {image}"
)


def _load_controls() -> list[dict]:
    lines = CONTROL_JSONL.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def _build_document(item: dict) -> str:
    return DOCUMENT_TEMPLATE.format(
        displayName=item["displayName"],
        width=item.get("width") or 0,
        height=item.get("height") or 0,
        image=item["image"],
    )


def _build_metadata(item: dict) -> dict:
    return {
        "type": "control",
        "displayName": item["displayName"],
        "width": item.get("width") or 0,
        "height": item.get("height") or 0,
        "image": item["image"],
    }


def _build_id(item: dict) -> str:
    return "control_{}".format(item["displayName"])


def get_collection(client: chromadb.ClientAPI) -> chromadb.Collection:
    ef = get_embedding_function()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def seed(client: chromadb.ClientAPI) -> None:
    controls = _load_controls()
    ids = [_build_id(item) for item in controls]
    documents = [_build_document(item) for item in controls]
    metadatas = [_build_metadata(item) for item in controls]

    collection = get_collection(client)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)


def query(client: chromadb.ClientAPI, query_text: str, n_results: int = 10) -> dict:
    collection = get_collection(client)
    return collection.query(query_texts=[query_text], n_results=n_results)


class ControlChunk:
    def __init__(self, chroma_dir: Optional[str] = None):
        if chroma_dir is None:
            chroma_dir = str(Path(__file__).resolve().parent / "db")

        self._client = chromadb.PersistentClient(path=chroma_dir)

    def seed(self) -> None:
        seed(self._client)

    def query(self, query_text: str, n_results: int = 10) -> dict:
        return query(self._client, query_text, n_results)

    def get_raw_controls(self) -> list[dict]:
        return _load_controls()
