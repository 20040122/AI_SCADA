from __future__ import annotations

import os
from typing import Any

os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["DEEPSEEK_MODEL"] = "test-model"

from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice


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
