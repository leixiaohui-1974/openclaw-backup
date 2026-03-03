#!/usr/bin/env python3
"""HydroMAS LLM Client — CLI 侧 LLM 调用封装。

纯 stdlib（urllib），零外部依赖，与 hydromas_call.py 同目录。
支持 DashScope OpenAI-compatible API。

用法（独立测试）:
    python3 llm_client.py "你好"
    python3 llm_client.py "氧化铝厂水网概述"
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

# ── Config (credentials from env vars) ──
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_MODEL = "qwen3.5-plus"

API_KEY = os.environ.get("HYDROMAS_LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
BASE_URL = os.environ.get("HYDROMAS_LLM_BASE_URL", _DEFAULT_BASE_URL)
MODEL = os.environ.get("HYDROMAS_LLM_MODEL", _DEFAULT_MODEL)

# ── Cache ──
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 600  # 10 minutes
_CACHE_MAX = 100


class LLMError(Exception):
    """LLM 调用错误。"""


def _cache_key(messages: list[dict], model: str, temperature: float) -> str:
    raw = json.dumps({"m": messages, "model": model, "t": temperature},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _evict_cache():
    """Remove expired entries; if still over limit, drop oldest."""
    now = time.time()
    expired = [k for k, (_, ts) in _cache.items() if now - ts > _CACHE_TTL]
    for k in expired:
        del _cache[k]
    while len(_cache) > _CACHE_MAX:
        oldest_k = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest_k]


def call_llm(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: int = 60,
    use_cache: bool = True,
) -> str | None:
    """调用 LLM，返回文本响应。失败返回 None（不抛异常）。

    Args:
        messages: OpenAI 格式消息列表
        model: 模型名（默认用环境变量或 qwen3.5-plus）
        temperature: 生成温度
        max_tokens: 最大 token 数
        timeout: 超时秒数
        use_cache: 是否使用内存缓存

    Returns:
        LLM 响应文本，失败返回 None
    """
    if not API_KEY or API_KEY.strip() == "":
        return None

    model = model or MODEL

    # Check cache
    if use_cache:
        ck = _cache_key(messages, model, temperature)
        if ck in _cache:
            resp, ts = _cache[ck]
            if time.time() - ts < _CACHE_TTL:
                return resp
            del _cache[ck]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    last_exc = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            last_exc = None
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep((attempt + 1) * 2)
                continue
            return None
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep((attempt + 1) * 2)
                continue
            return None

    if last_exc:
        return None

    # Store in cache
    if use_cache:
        _evict_cache()
        _cache[ck] = (text, time.time())

    return text


def call_llm_json(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    temperature: float = 0.1,
    max_tokens: int = 512,
    timeout: int = 60,
    use_cache: bool = True,
) -> dict | None:
    """调用 LLM 并解析 JSON 响应。兼容 markdown 代码块包裹。

    Returns:
        解析后的 dict，失败返回 None
    """
    text = call_llm(
        messages, model=model, temperature=temperature,
        max_tokens=max_tokens, timeout=timeout, use_cache=use_cache,
    )
    if text is None:
        return None

    # Strip markdown code block wrapper if present
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        stripped = "\n".join(lines).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Try to find JSON object in text
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None


# ── CLI test ──
if __name__ == "__main__":
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "你好，请简单介绍一下你自己。"
    print(f"Model: {MODEL}")
    if API_KEY:
        print(f"API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    else:
        print("API Key: (not set; configure HYDROMAS_LLM_API_KEY or DASHSCOPE_API_KEY)")
    print(f"Base URL: {BASE_URL}")
    print(f"Prompt: {prompt}\n")

    result = call_llm([{"role": "user", "content": prompt}], timeout=30)
    if result:
        print(f"Response:\n{result}")
    else:
        print("ERROR: LLM call failed (returned None)")
        sys.exit(1)

    # Test JSON mode
    print("\n--- JSON mode test ---")
    json_result = call_llm_json([
        {"role": "system", "content": "只返回JSON，不要其他文本。"},
        {"role": "user", "content": '判断"分析用水情况"的意图，返回 {"intent": "...", "confidence": 0.0-1.0}'},
    ])
    if json_result:
        print(f"JSON result: {json.dumps(json_result, ensure_ascii=False)}")
    else:
        print("WARNING: JSON parse failed")
