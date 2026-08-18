from __future__ import annotations

import json
import logging
import unicodedata

from openai import APIConnectionError, APITimeoutError

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """\
你是工业SCADA控件检索专家。从用户的自然语言描述中提取所需的控件名称。
控件库中可用的控件名称列表（仅供参考，禁止改写）：
{control_names}
提取要求：
1. 只拆分并返回用户原文中连续出现的肯定需求词
2. 禁止改写成控件库中的名称，也不得为库外词寻找最接近的控件
3. 忽略数量、语气词以及否定、举例、比较等语句
4. 同一个需求词只输出一次
5. 每个需求词必须是用户原文中的连续片段
示例：
用户: 2个指示灯和1个水泵
输出: {{"controls": ["指示灯", "水泵"]}}
用户: 组态画面需要显示温度和压力
输出: {{"controls": ["温度", "压力"]}}
输出JSON:
{{"controls": ["需求词"]}}
"""

EXTRACT_PROMPT_VERSION = "2"


class ControlModelOutputError(RuntimeError):
    pass


class ControlModelUnavailableError(RuntimeError):
    pass


class ControlModelTimeoutError(RuntimeError):
    pass


def normalize_term(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def validate_extracted_words(query: str, raw_values):
    if not isinstance(raw_values, list):
        return None, ["controls 必须是数组"]
    norm_query = normalize_term(query)
    seen = set()
    items = []
    errors = []
    for value in raw_values:
        if not isinstance(value, str):
            errors.append("存在非字符串元素")
            continue
        word = value.strip()
        if not word:
            continue
        norm_word = normalize_term(word)
        if norm_word in seen:
            continue
        if norm_word not in norm_query:
            errors.append("词不在原文中: " + word)
            continue
        seen.add(norm_word)
        items.append((norm_query.index(norm_word), word))
    if errors:
        return None, errors
    items.sort(key=lambda item: item[0])
    return [word for _, word in items], []


async def extract_control_words(client, model, query, control_names_str):
    key = _extract_cache_key(query, model, control_names_str)
    if key in _extract_cache:
        return list(_extract_cache[key]), True
    prompt = EXTRACT_PROMPT.format(control_names=control_names_str)
    words = await _extract_with_retry(client, model, query, prompt)
    _extract_cache[key] = list(words)
    return words, False


async def _extract_with_retry(client, model, query, prompt):
    last_errors = []
    empty_attempts = 0
    for _ in range(2):
        try:
            raw = await _call_model(client, model, query, prompt)
        except (ControlModelUnavailableError, ControlModelTimeoutError):
            raise
        except Exception as exc:
            raise ControlModelOutputError("模型调用失败: " + str(exc)) from exc
        words, errors = validate_extracted_words(query, raw)
        if errors:
            last_errors = errors
            continue
        if not words:
            empty_attempts += 1
            continue
        return words
    if last_errors and empty_attempts == 0:
        raise ControlModelOutputError("模型输出校验失败: " + "; ".join(last_errors))
    return []


async def _call_model(client, model, query, prompt):
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            stream=False,
            reasoning_effort="low",
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
    except APITimeoutError as exc:
        raise ControlModelTimeoutError("模型请求超时") from exc
    except APIConnectionError as exc:
        raise ControlModelUnavailableError("模型服务不可用") from exc
    content = response.choices[0].message.content or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ControlModelOutputError("模型输出非法 JSON") from exc
    if not isinstance(data, dict):
        raise ControlModelOutputError("模型输出结构非法")
    return data.get("controls")


def _extract_cache_key(query, model, control_names_str):
    return (query, model, EXTRACT_PROMPT_VERSION, control_names_str)


def clear_extract_cache():
    _extract_cache.clear()


_extract_cache: dict = {}
