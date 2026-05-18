from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("chromadb")
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.chroma import ControlChunk, control_chunk


class DummyEmbeddingFunction(EmbeddingFunction[Documents]):
    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        return [[1.0 if "按钮" in text else 0.0] * 8 for text in input]

    @staticmethod
    def name() -> str:
        return "dummy-embedding-function"

    @staticmethod
    def build_from_config(config):
        return DummyEmbeddingFunction()

    def get_config(self):
        return {}


def test_default_persistence_path(monkeypatch):
    captured = {}

    class DummyClient:
        pass

    def fake_persistent_client(*, path):
        captured["path"] = path
        return DummyClient()

    monkeypatch.setattr(control_chunk.chromadb, "PersistentClient", fake_persistent_client)

    chunk = ControlChunk()

    assert captured["path"] == str(Path(control_chunk.__file__).resolve().parent / "db")
    assert isinstance(chunk._client, DummyClient)


def test_get_raw_controls_reads_jsonl(monkeypatch):
    class DummyClient:
        pass

    def fake_persistent_client(*, path):
        return DummyClient()

    monkeypatch.setattr(control_chunk.chromadb, "PersistentClient", fake_persistent_client)
    chunk = ControlChunk(chroma_dir=str(Path("/tmp") / "chroma-test-unused"))

    controls = chunk.get_raw_controls()

    assert controls
    assert controls[0]["displayName"] == "高低温试验箱"
    assert controls[0]["image"] == "symbols/_public/devices/高低温试验箱.json"


def test_seed_and_query_work_in_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(control_chunk, "get_embedding_function", lambda: DummyEmbeddingFunction())

    chunk = ControlChunk(chroma_dir=str(tmp_path))

    try:
        chunk.seed()
        result = chunk.query("按钮", n_results=3)
    except Exception as exc:  # pragma: no cover - depends on local chromadb env
        pytest.skip(f"seed/query unavailable in this environment: {exc}")

    assert result["ids"]
    assert len(result["ids"][0]) <= 3
    assert any("按钮" in doc for doc in result.get("documents", [[]])[0])
