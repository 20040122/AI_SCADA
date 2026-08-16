from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chromadb

from data.chroma.control_chunk import QUERY_PREFIX
from data.chroma.embedding import get_embedding_function
from model.control_tools.extract import normalize_term

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
CONTROL_JSONL = ROOT / "data" / "control.jsonl"
CONTROL_MAPPINGS = ROOT / "data" / "control_mappings.json"

COLLECTION_PREFIX = "control_chunks_v_"

DOCUMENT_TEMPLATE = (
    "SCADA 控件：{displayName}，宽度 {width}，高度 {height}，资源路径 {image}"
)

_COLLECTION_METADATA = {
    "hnsw:space": "cosine",
    "hnsw:construction_ef": 200,
    "hnsw:M": 32,
    "hnsw:search_ef": 100,
}


class CatalogConfigError(ValueError):
    pass


class CatalogCorruptError(RuntimeError):
    pass


@dataclass
class CatalogSnapshot:
    control_hash: str
    names: list[str]
    controls: dict[str, dict]
    controls_by_norm: dict[str, dict]
    mappings: dict[str, list[str]]
    collection: chromadb.Collection
    refcount: int = 0
    retired: bool = False


def load_canonical_controls(jsonl_path) -> list[dict]:
    lines = Path(jsonl_path).read_text(encoding="utf-8").strip().splitlines()
    controls = []
    seen = set()
    for line in lines:
        item = json.loads(line)
        name = item.get("displayName")
        if not isinstance(name, str) or not name:
            raise CatalogConfigError("无效控件行（缺少 displayName）")
        if name in seen:
            logger.warning("control.jsonl 重复 displayName，最后一条为规范素材: %s", name)
        seen.add(name)
        controls.append(item)
    canonical = {}
    for item in controls:
        canonical[item["displayName"]] = item
    return list(canonical.values())


def parse_mappings(mappings_path, canonical_names) -> dict[str, list[str]]:
    raw = json.loads(Path(mappings_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CatalogConfigError("映射文件必须是 JSON 对象")
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise CatalogConfigError("映射文件缺少有效 version")
    items = raw.get("mappings")
    if not isinstance(items, list):
        raise CatalogConfigError("mappings 必须是数组")
    name_set = set(canonical_names)
    norm_names = {normalize_term(name) for name in name_set}
    seen_terms = set()
    mappings = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise CatalogConfigError(f"映射项 {index} 必须是对象")
        term = item.get("term")
        targets = item.get("targets")
        if not isinstance(term, str) or not term.strip():
            raise CatalogConfigError(f"映射项 {index} 缺少非空 term")
        if not isinstance(targets, list) or not targets:
            raise CatalogConfigError(f"映射项 {index} 的 targets 不能为空")
        if len(targets) > 5:
            raise CatalogConfigError(f"映射项 {index} 的 targets 超过 5 个")
        for target in targets:
            if not isinstance(target, str) or not target.strip():
                raise CatalogConfigError(f"映射项 {index} 存在空目标")
            if target not in name_set:
                raise CatalogConfigError(f"映射项 {index} 的未知目标: {target}")
        if len(set(targets)) != len(targets):
            raise CatalogConfigError(f"映射项 {index} 的 targets 必须唯一")
        norm_term = normalize_term(term)
        if norm_term in seen_terms:
            raise CatalogConfigError(f"重复映射键: {term}")
        if norm_term in norm_names:
            raise CatalogConfigError(f"映射键与控件名冲突: {term}")
        seen_terms.add(norm_term)
        mappings[norm_term] = list(targets)
    return mappings


def _hash_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


class ControlCatalogManager:
    def __init__(
        self,
        chroma_dir: Optional[str] = None,
        control_jsonl_path: Optional[str] = None,
        mappings_path: Optional[str] = None,
        embedding_function=None,
    ):
        if chroma_dir is None:
            chroma_dir = str(ROOT / "data" / "chroma" / "db")
        self._client = chromadb.PersistentClient(path=chroma_dir)
        self._jsonl_path = Path(control_jsonl_path) if control_jsonl_path else CONTROL_JSONL
        self._mappings_path = Path(mappings_path) if mappings_path else CONTROL_MAPPINGS
        self._ef = embedding_function if embedding_function is not None else get_embedding_function()
        self._current: Optional[CatalogSnapshot] = None
        self._control_hash = ""
        self._mappings_hash = ""
        self._reload_lock = asyncio.Lock()

    def load_initial(self) -> None:
        self._current = self._build_snapshot()
        self._control_hash = _hash_file(self._jsonl_path)
        self._mappings_hash = _hash_file(self._mappings_path)
        logger.info("控件目录快照加载完成（%d 个控件）", len(self._current.names))

    async def acquire(self) -> CatalogSnapshot:
        async with self._reload_lock:
            await asyncio.to_thread(self._maybe_reload)
        snap = self._current
        snap.refcount += 1
        return snap

    def release(self, snap: CatalogSnapshot) -> None:
        snap.refcount -= 1
        if snap.retired and snap.refcount <= 0:
            self._retire_collection(snap)

    def close(self) -> None:
        if self._current is not None:
            self._delete_collection(self._current)
            self._current = None
        try:
            self._client.close()
        except Exception:
            logger.warning("关闭 Chroma 客户端失败")

    def _retire_collection(self, snap: CatalogSnapshot) -> None:
        if self._current is not None and self._current.collection is snap.collection:
            return
        self._delete_collection(snap)

    def _maybe_reload(self) -> None:
        control_hash = _hash_file(self._jsonl_path)
        mappings_hash = _hash_file(self._mappings_path)
        if control_hash == self._control_hash and mappings_hash == self._mappings_hash:
            return
        try:
            if control_hash != self._control_hash:
                new_snap = self._build_snapshot()
            else:
                new_snap = self._build_mapping_snapshot(mappings_hash)
        except Exception as exc:
            logger.warning(
                "控件目录热更新失败: control_hash=%s mappings_hash=%s 原因=%s; 继续使用上一份快照",
                control_hash,
                mappings_hash,
                exc,
            )
            return
        old = self._current
        self._current = new_snap
        self._control_hash = control_hash
        self._mappings_hash = mappings_hash
        if old is not None:
            old.retired = True
            if old.refcount <= 0:
                self._retire_collection(old)

    def _build_snapshot(self) -> CatalogSnapshot:
        controls = load_canonical_controls(self._jsonl_path)
        names = [item["displayName"] for item in controls]
        mappings = parse_mappings(self._mappings_path, names)
        control_hash = _hash_file(self._jsonl_path)
        collection = self._ensure_collection(controls, control_hash)
        return CatalogSnapshot(
            control_hash=control_hash,
            names=names,
            controls={item["displayName"]: item for item in controls},
            controls_by_norm={normalize_term(item["displayName"]): item for item in controls},
            mappings=mappings,
            collection=collection,
        )

    def _build_mapping_snapshot(self, mappings_hash: str) -> CatalogSnapshot:
        if self._current is None:
            raise CatalogConfigError("没有可用快照")
        mappings = parse_mappings(self._mappings_path, self._current.names)
        return CatalogSnapshot(
            control_hash=self._current.control_hash,
            names=list(self._current.names),
            controls=dict(self._current.controls),
            controls_by_norm=dict(self._current.controls_by_norm),
            mappings=mappings,
            collection=self._current.collection,
        )

    def _ensure_collection(self, controls: list[dict], control_hash: str):
        name = COLLECTION_PREFIX + control_hash
        try:
            collection = self._client.get_collection(name=name)
        except Exception:
            collection = None
        ids = [_build_id(item) for item in controls]
        if collection is None or collection.count() != len(ids):
            if collection is not None:
                self._client.delete_collection(name)
            collection = self._client.create_collection(
                name=name,
                embedding_function=self._ef,
                metadata=dict(_COLLECTION_METADATA),
            )
            collection.upsert(
                ids=ids,
                documents=[_build_document(item) for item in controls],
                metadatas=[_build_metadata(item) for item in controls],
            )
        got = collection.get(ids=ids, include=["metadatas"])
        got_ids = got.get("ids") or []
        got_metas = got.get("metadatas") or []
        if len(got_ids) != len(ids):
            raise CatalogCorruptError("控件集合元数据数量不完整")
        meta_by_id = dict(zip(got_ids, got_metas))
        for item in controls:
            meta = meta_by_id.get(_build_id(item))
            if meta is None or meta.get("displayName") != item["displayName"]:
                raise CatalogCorruptError("控件集合元数据与清单不一致")
        return collection

    def _delete_collection(self, snap: CatalogSnapshot) -> None:
        name = snap.collection.name
        if not name.startswith(COLLECTION_PREFIX):
            return
        try:
            self._client.delete_collection(name)
        except Exception:
            logger.warning("删除退休集合失败: %s", name)
