"""LLM abstraction. Any OpenAI-compatible /chat/completions endpoint works (OpenAI, Groq, OpenRouter, Ollama...)."""
from __future__ import annotations

import json
import re
from typing import Protocol

import requests

from core.errors import LLMError
from core.logging import get_logger, register_secret

log = get_logger("llm")


class LLMClient(Protocol):
    name: str

    def complete_json(self, stage: str, system: str, payload: dict) -> dict: ...


def parse_json_object(text: str) -> dict:
    """Extract a JSON object from model output, tolerating markdown fences and stray prose."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value is not an object")
    return data


class OpenAICompatibleClient:
    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 90):
        if not api_key:
            raise LLMError("LLM_API_KEY is not set. Add it to your .env file or enter it in the sidebar.")
        register_secret(api_key)
        self._key, self.model, self.timeout = api_key, model, timeout
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.name = f"{model} @ {base_url}"

    def complete_json(self, stage: str, system: str, payload: dict) -> dict:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        last_problem = "unknown error"
        for attempt in range(2):
            try:
                resp = requests.post(
                    self.url, json=body, timeout=self.timeout,
                    headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                )
            except requests.Timeout:
                raise LLMError(f"LLM request timed out after {self.timeout}s.") from None
            except requests.RequestException as exc:
                raise LLMError(f"Could not reach the LLM endpoint: {type(exc).__name__}.") from None

            if resp.status_code == 400 and "response_format" in body:
                body.pop("response_format")  # some providers don't support JSON mode
                last_problem = "provider rejected response_format"
                continue
            if resp.status_code in (401, 403):
                raise LLMError("LLM authentication failed. Check LLM_API_KEY.")
            if resp.status_code == 429:
                raise LLMError("LLM rate limit reached. Wait a moment and retry.")
            if resp.status_code >= 400:
                raise LLMError(f"LLM returned HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                content = resp.json()["choices"][0]["message"]["content"]
                log.info("llm stage=%s ok", stage)
                return parse_json_object(content)
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                last_problem = f"malformed response ({exc})"
                body["messages"].append({"role": "user", "content": "Your reply was not valid JSON. Reply with ONLY the JSON object."})
        raise LLMError(f"LLM gave an unusable response at stage '{stage}': {last_problem}.")
