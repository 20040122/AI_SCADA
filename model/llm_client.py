from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv(".env.local")

default_client = AsyncOpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    timeout=60.0,
)

default_model = os.environ.get("DEEPSEEK_MODEL")

_RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    reraise=True,
)
async def call_llm(client, model, messages, **kwargs):
    return await client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )
