"""AI Provider abstraction.

Pluggable backend. The built-in OpenAICompatProvider talks to any
OpenAI-compatible /v1/chat/completions endpoint (OpenAI, Ollama, LM Studio,
vLLM, Groq, DeepSeek, ...). Uses only the stdlib (urllib) so the extension
needs no pip dependencies.

Pure Python; importable headless. Network calls obviously only work online.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional


class AIProvider:
    """Subclass to add a new backend."""
    name = "abstract"

    def complete(self, messages: List[Dict[str, str]], **opts) -> str:
        raise NotImplementedError


class OpenAICompatProvider(AIProvider):
    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str = "", model: str = "gpt-4o-mini",
                 timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages: List[Dict[str, str]], *, temperature: float = 0.7,
                 max_tokens: int = 512, model: Optional[str] = None, **_) -> str:
        url = f"{self.base_url}/chat/completions"
        body = json.dumps({
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络错误: {e.reason}")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise RuntimeError(f"返回格式异常: {str(data)[:200]}")


# provider registry so future backends slot in
PROVIDERS: Dict[str, type] = {"openai-compat": OpenAICompatProvider}


def make_provider(kind: str, **kw) -> AIProvider:
    cls = PROVIDERS.get(kind, OpenAICompatProvider)
    return cls(**kw)
