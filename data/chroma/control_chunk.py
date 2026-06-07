import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import chromadb
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from data.chroma.embedding import get_embedding_function

logger = logging.getLogger(__name__)

CONTROL_JSONL = Path(__file__).resolve().parent.parent / "control.jsonl"

COLLECTION_NAME = "control_chunks"

DOCUMENT_TEMPLATE = (
    "SCADA 控件：{displayName}，宽度 {width}，高度 {height}，资源路径 {image}"
)

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def _load_controls(jsonl_path: Optional[Path] = None) -> list[dict]:
    path = jsonl_path or CONTROL_JSONL
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def _build_document(item: dict) -> str:
    content = DOCUMENT_TEMPLATE.format(
        displayName=item["displayName"],
        width=item.get("width") or 0,
        height=item.get("height") or 0,
        image=item["image"],
    )
    return QUERY_PREFIX + content


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


def _compute_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    prefixed_query = QUERY_PREFIX + query_text
    return collection.query(query_texts=[prefixed_query], n_results=n_results)


class _ControlJsonlHandler(FileSystemEventHandler):
    def __init__(self, chunk: "ControlChunk"):
        self._chunk = chunk

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name == "control.jsonl":
            self._chunk.check_and_reseed()

    def on_created(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name == "control.jsonl":
            self._chunk.check_and_reseed()

    def on_moved(self, event):
        dest = getattr(event, "dest_path", None)
        if dest and Path(dest).name == "control.jsonl":
            self._chunk.check_and_reseed()


class ControlChunk:
    def __init__(
        self,
        chroma_dir: Optional[str] = None,
        control_jsonl_path: Optional[str] = None,
    ):
        if chroma_dir is None:
            chroma_dir = str(Path(__file__).resolve().parent / "db")

        self._client = chromadb.PersistentClient(path=chroma_dir)
        self._jsonl_path = Path(control_jsonl_path) if control_jsonl_path else CONTROL_JSONL
        self._file_hash = _compute_file_hash(self._jsonl_path)
        self._observer: Optional[Observer] = None

    def seed(self) -> None:
        controls = _load_controls(self._jsonl_path)
        ids = [_build_id(item) for item in controls]
        documents = [_build_document(item) for item in controls]
        metadatas = [_build_metadata(item) for item in controls]

        collection = get_collection(self._client)
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def reseed(self) -> None:
        controls = _load_controls(self._jsonl_path)
        ids = [_build_id(item) for item in controls]
        documents = [_build_document(item) for item in controls]
        metadatas = [_build_metadata(item) for item in controls]

        collection = get_collection(self._client)

        existing_ids = collection.get(include=[])["ids"]
        new_id_set = set(ids)
        stale_ids = [eid for eid in existing_ids if eid not in new_id_set]

        if stale_ids:
            collection.delete(ids=stale_ids)
            logger.info("ChromaDB 移除 %d 个已删除控件", len(stale_ids))

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        self._file_hash = _compute_file_hash(self._jsonl_path)
        logger.info("ChromaDB 全量同步完成（%d 个控件）", len(controls))

    def check_and_reseed(self) -> bool:
        current_hash = _compute_file_hash(self._jsonl_path)
        if current_hash == self._file_hash:
            return False
        logger.info("control.jsonl 内容已变更，触发 ChromaDB 全量同步...")
        self.reseed()
        return True

    def query(self, query_text: str, n_results: int = 10) -> dict:
        collection = get_collection(self._client)
        prefixed_query = QUERY_PREFIX + query_text
        return collection.query(query_texts=[prefixed_query], n_results=n_results)

    def get_raw_controls(self) -> list[dict]:
        return _load_controls(self._jsonl_path)

    def start_watcher(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        event_handler = _ControlJsonlHandler(self)
        watch_dir = str(self._jsonl_path.parent)
        self._observer.schedule(event_handler, watch_dir, recursive=False)
        self._observer.start()
        logger.info("control.jsonl 文件监听已启动 (%s)", watch_dir)

    def stop_watcher(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        logger.info("control.jsonl 文件监听已停止")
