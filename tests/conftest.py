from __future__ import annotations

import hashlib
import os
from typing import Any

os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["DEEPSEEK_MODEL"] = "test-model"

from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice


class FakeEmbedding:
    def __init__(self, dimension: int = 16):
        self._dimension = dimension

    def _embed_texts(self, input):
        result = []
        for text in input:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vec = []
            for byte in digest[:4]:
                for shift in range(8):
                    vec.append(1.0 if (byte & (1 << shift)) else -1.0)
            norm = len(vec) ** 0.5
            result.append([v / norm for v in vec])
        return result

    def embed_query(self, input):
        return self._embed_texts(input)

    def embed_documents(self, input):
        return self._embed_texts(input)

    def __call__(self, input):
        return self._embed_texts(input)


def _make_choice(content: str = "") -> Choice:
    msg = ChatCompletionMessage(role="assistant", content=content)
    return Choice(finish_reason="stop", index=0, message=msg)


def make_fake_completion(content: str = "") -> ChatCompletion:
    return ChatCompletion(
        id="test",
        choices=[_make_choice(content)],
        created=0,
        model="test",
        object="chat.completion",
    )


class FakeAsyncClient:
    def __init__(self, responses: list[Any] | None = None):
        self._responses = responses or []
        self._call_count = 0
        self._raise_on_call: dict[int, Exception] = {}

    def set_failure(self, call_index: int, exc: Exception) -> None:
        self._raise_on_call[call_index] = exc

    def fail_times(self, count: int, exc: Exception) -> None:
        for i in range(count):
            self._raise_on_call[i] = exc

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    @property
    def create(self):
        return self

    async def __call__(self, *args, **kwargs):
        idx = self._call_count
        self._call_count += 1
        if idx in self._raise_on_call:
            raise self._raise_on_call.pop(idx)
        if self._responses:
            return self._responses.pop(0)
        return make_fake_completion()

    def with_options(self, **kwargs):
        return self
