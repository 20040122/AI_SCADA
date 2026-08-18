from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional
import httpx

from data.sqlite.material_db import MaterialDB
from model.control_tools.catalog import ControlCatalogManager
from model.control_tools.extract import normalize_term
from picture.qwen import GenerationError, generate_control_image

MAX_SEED = 2 ** 31 - 1

logger = logging.getLogger(__name__)


class GenerationStatus:
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class GenerationAPIError(Exception):
    def __init__(self, message: str, status_code: int, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise GenerationAPIError("控件名称不能为空", 400, "invalid_name")
    if len(name) > 64:
        raise GenerationAPIError("控件名称长度不能超过 64 个字符", 400, "invalid_name")
    if "/" in name or "\\" in name:
        raise GenerationAPIError("控件名称不能包含 / 或 \\", 400, "invalid_name")
    if name in (".", ".."):
        raise GenerationAPIError("控件名称不能为 . 或 ..", 400, "invalid_name")
    for ch in name:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise GenerationAPIError("控件名称不能包含控制字符", 400, "invalid_name")
    return name


@dataclass
class GenerationTask:
    generation_id: str
    query: str
    name: str
    seed: int
    status: str = GenerationStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    ready_at: Optional[float] = None
    expires_at: Optional[float] = None
    preview_path: Optional[Path] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class AssetUploader:
    def __init__(self, base_url: str, timeout: float):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def upload(self, name: str, png_path: Path) -> None:
        target_path = f"assets/Agent/{name}.png"
        data_url = "data:image/png;base64," + base64.b64encode(png_path.read_bytes()).decode("ascii")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._base_url,
                    files=[
                        ("path", (None, target_path)),
                        ("content", (None, data_url)),
                    ],
                )
        except httpx.TimeoutException as exc:
            raise GenerationAPIError("DaoSCADA 上传超时", 504, "upload_timeout") from exc
        except httpx.HTTPError as exc:
            raise GenerationAPIError(f"DaoSCADA 上传失败: {exc}", 502, "upload_failed") from exc
        if not 200 <= response.status_code < 300:
            raise GenerationAPIError(
                f"DaoSCADA 上传被拒绝: HTTP {response.status_code}", 502, "upload_failed"
            )


def make_default_generator(reference_path: Path, timeout: float) -> Callable[[str, int, Path], None]:
    def generate(name: str, seed: int, output_path: Path) -> None:
        generate_control_image(
            name=name,
            reference_path=reference_path,
            output_path=output_path,
            seed=seed,
            size="1024*1024",
            timeout=timeout,
        )

    return generate


class GenerationManager:
    def __init__(
        self,
        temp_dir: Path,
        ttl_seconds: float,
        generator: Callable[[str, int, Path], None],
        uploader: AssetUploader,
        jsonl_path: Path,
        catalog: ControlCatalogManager,
        db: MaterialDB,
        cleanup_interval: float = 30.0,
    ):
        self._temp_dir = Path(temp_dir)
        self._ttl_seconds = ttl_seconds
        self._generator = generator
        self._uploader = uploader
        self._jsonl_path = Path(jsonl_path)
        self._catalog = catalog
        self._db = db
        self._cleanup_interval = cleanup_interval
        self._tasks: Dict[str, GenerationTask] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._confirm_lock = asyncio.Lock()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        for png in self._temp_dir.glob("*.png"):
            png.unlink(missing_ok=True)
        self._tasks.clear()
        self._running = True
        self._worker_task = asyncio.create_task(self._run_worker())
        self._cleanup_task = asyncio.create_task(self._run_cleanup())

    async def stop(self) -> None:
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    def create(self, query: str, name: str) -> GenerationTask:
        valid_name = validate_name(name)
        if self._has_name_conflict(valid_name):
            raise GenerationAPIError(f"同名控件已存在: {valid_name}", 409, "conflict")
        generation_id = uuid.uuid4().hex
        task = GenerationTask(
            generation_id=generation_id,
            query=query,
            name=valid_name,
            seed=secrets.randbelow(MAX_SEED),
        )
        self._tasks[generation_id] = task
        self._queue.put_nowait(generation_id)
        return task

    def get(self, generation_id: str) -> Optional[GenerationTask]:
        return self._tasks.get(generation_id)

    def regenerate(self, generation_id: str) -> GenerationTask:
        task = self._get_task(generation_id)
        if task.status in (GenerationStatus.QUEUED, GenerationStatus.RUNNING):
            raise GenerationAPIError("任务正在生成中，不能重新生成", 409, "conflict")
        if task.status in (GenerationStatus.CONFIRMED, GenerationStatus.DISCARDED):
            raise GenerationAPIError("任务已结束，不能重新生成", 409, "conflict")
        if task.status == GenerationStatus.EXPIRED:
            raise GenerationAPIError("任务已过期，不能重新生成", 410, "expired")
        self._delete_preview(task)
        task.seed = secrets.randbelow(MAX_SEED)
        task.status = GenerationStatus.QUEUED
        task.error = None
        task.error_code = None
        task.ready_at = None
        task.expires_at = None
        self._queue.put_nowait(generation_id)
        return task

    def discard(self, generation_id: str) -> None:
        task = self._get_task(generation_id)
        if task.status == GenerationStatus.CONFIRMED:
            raise GenerationAPIError("已确认任务不能放弃", 409, "conflict")
        task.status = GenerationStatus.DISCARDED
        self._delete_preview(task)

    def get_preview_path(self, generation_id: str) -> Path:
        task = self._get_task(generation_id)
        if task.status == GenerationStatus.EXPIRED:
            raise GenerationAPIError("任务已过期", 410, "expired")
        if task.status == GenerationStatus.READY:
            if self._is_expired(task):
                task.status = GenerationStatus.EXPIRED
                self._delete_preview(task)
                raise GenerationAPIError("任务已过期", 410, "expired")
            if task.preview_path is None:
                raise GenerationAPIError("预览文件缺失", 500, "preview_missing")
            return task.preview_path
        if task.status in (GenerationStatus.CONFIRMED, GenerationStatus.DISCARDED):
            raise GenerationAPIError("预览已删除", 404, "not_found")
        raise GenerationAPIError("任务尚未完成", 409, "not_ready")

    async def confirm(self, generation_id: str) -> dict:
        async with self._confirm_lock:
            task = self._get_task(generation_id)
            if task.status == GenerationStatus.EXPIRED:
                raise GenerationAPIError("任务已过期", 410, "expired")
            if task.status == GenerationStatus.CONFIRMED:
                raise GenerationAPIError("任务已确认", 409, "conflict")
            if task.status != GenerationStatus.READY:
                raise GenerationAPIError("任务尚未完成，无法确认", 409, "not_ready")
            if self._is_expired(task):
                task.status = GenerationStatus.EXPIRED
                self._delete_preview(task)
                raise GenerationAPIError("任务已过期", 410, "expired")
            if self._has_name_conflict(task.name):
                raise GenerationAPIError(f"同名控件已存在: {task.name}", 409, "conflict")
            preview = task.preview_path
            if preview is None:
                raise GenerationAPIError("预览文件缺失", 500, "preview_missing")
            await self._uploader.upload(task.name, preview)
            record = {
                "displayName": task.name,
                "image": f"assets/Agent/{task.name}.png",
                "width": 128,
                "height": 128,
                "source": "ai-generated",
                "similarity": 1.0,
            }
            jsonl_record = {
                "displayName": record["displayName"],
                "image": record["image"],
                "width": record["width"],
                "height": record["height"],
            }
            try:
                self._append_jsonl(jsonl_record)
                reload_ok = await self._verify_catalog_reload(task.name)
                if not reload_ok:
                    raise GenerationAPIError("控件目录热更新未生效", 502, "catalog_reload_failed")
                await self._db.confirm_generated(
                    name=task.name, image=record["image"], query=task.query
                )
            except GenerationAPIError:
                raise
            except Exception as exc:
                logger.error("确认入库本地操作失败: name=%s %s", task.name, exc)
                raise GenerationAPIError(f"确认入库失败: {exc}", 502, "persist_failed") from exc
            path = task.preview_path
            task.status = GenerationStatus.CONFIRMED
            task.preview_path = None
            task.ready_at = None
            task.expires_at = None
            if path is not None:
                path.unlink(missing_ok=True)
            return record

    def to_dict(self, task: GenerationTask) -> dict:
        preview_url = None
        if task.status == GenerationStatus.READY and not self._is_expired(task):
            preview_url = f"/api/control/generations/{task.generation_id}/preview"
        return {
            "generation_id": task.generation_id,
            "name": task.name,
            "status": task.status,
            "seed": task.seed,
            "created_at": self._to_iso(task.created_at),
            "expires_at": self._to_iso(task.expires_at),
            "preview_url": preview_url,
            "error": task.error,
            "error_code": task.error_code,
        }

    @staticmethod
    def _to_iso(ts: Optional[float]) -> Optional[str]:
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def _get_task(self, generation_id: str) -> GenerationTask:
        task = self._tasks.get(generation_id)
        if task is None:
            raise GenerationAPIError("生成任务不存在", 404, "not_found")
        return task

    def _is_expired(self, task: GenerationTask) -> bool:
        return (
            task.status == GenerationStatus.READY
            and task.expires_at is not None
            and time.time() >= task.expires_at
        )

    def _has_name_conflict(self, name: str) -> bool:
        norm = normalize_term(name)
        if not self._jsonl_path.exists():
            return False
        for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            display_name = item.get("displayName")
            if isinstance(display_name, str) and normalize_term(display_name) == norm:
                return True
        return False

    def _append_jsonl(self, record: dict) -> None:
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        if self._jsonl_path.exists() and self._jsonl_path.stat().st_size > 0:
            with open(self._jsonl_path, "rb") as fh:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    line = b"\n" + line
        with open(self._jsonl_path, "ab") as fh:
            fh.write(line)

    async def _verify_catalog_reload(self, name: str) -> bool:
        snap = await self._catalog.acquire()
        try:
            return normalize_term(name) in snap.controls_by_norm
        finally:
            self._catalog.release(snap)

    def _delete_preview(self, task: GenerationTask) -> None:
        if task.preview_path is not None:
            task.preview_path.unlink(missing_ok=True)
            task.preview_path = None

    async def _run_worker(self) -> None:
        while self._running:
            generation_id = await self._queue.get()
            try:
                task = self._tasks.get(generation_id)
                if task is None or task.status != GenerationStatus.QUEUED:
                    continue
                task.status = GenerationStatus.RUNNING
                output = self._temp_dir / f"{generation_id}.png"
                try:
                    await asyncio.to_thread(self._generator, task.name, task.seed, output)
                except GenerationError as exc:
                    task.status = GenerationStatus.FAILED
                    task.error = str(exc)
                    task.error_code = exc.code
                    output.unlink(missing_ok=True)
                    continue
                except Exception as exc:
                    task.status = GenerationStatus.FAILED
                    task.error = str(exc)
                    task.error_code = "generation_error"
                    output.unlink(missing_ok=True)
                    continue
                task.preview_path = output
                task.ready_at = time.time()
                task.expires_at = task.ready_at + self._ttl_seconds
                task.status = GenerationStatus.READY
            finally:
                self._queue.task_done()

    async def _run_cleanup(self) -> None:
        while self._running:
            await asyncio.sleep(self._cleanup_interval)
            now = time.time()
            for task in list(self._tasks.values()):
                if (
                    task.status == GenerationStatus.READY
                    and task.expires_at is not None
                    and now >= task.expires_at
                ):
                    task.status = GenerationStatus.EXPIRED
                    self._delete_preview(task)
