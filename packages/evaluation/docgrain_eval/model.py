"""Explicit OpenAI-compatible chat client."""

import time

import httpx

from .scoring import parse_json


class ChatClient:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 60,
                 retries: int = 3, transport: httpx.BaseTransport | None = None):
        self.model = model
        self.retries = retries
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self):
        self.client.close()

    def complete(self, messages: list[dict]) -> tuple[str, dict | None, dict]:
        payload = {"model": self.model, "messages": messages, "temperature": 0,
                   "response_format": {"type": "json_object"}}
        for attempt in range(self.retries + 1):
            response = self.client.post("chat/completions", json=payload)
            if response.status_code in {400, 422} and "response_format" in payload:
                payload.pop("response_format")
                response = self.client.post("chat/completions", json=payload)
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            response.raise_for_status()
            body = response.json()
            raw = body["choices"][0]["message"]["content"]
            if isinstance(raw, list):
                raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
            try:
                parsed = parse_json(raw)
            except (ValueError, TypeError):
                parsed = None
            return raw, parsed, body.get("usage") or {}
        raise RuntimeError("unreachable")
