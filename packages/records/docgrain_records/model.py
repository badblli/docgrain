"""Explicit, opt-in OpenAI-compatible client, following docgrain_eval.model."""

import time

import httpx

from .schema import proposal_schema


class ModelResponseError(ValueError):
    """Malformed/invalid model output; never expose its untrusted content in errors."""


class ChatClient:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 60,
                 retries: int = 3, transport: httpx.BaseTransport | None = None,
                 reasoning_effort: str | None = None, max_tokens: int | None = None,
                 on_usage=None):
        if not base_url or not model or not api_key:
            raise ValueError("model calls require explicit base_url, model and api_key")
        if retries < 0:
            raise ValueError("retries must be nonnegative")
        self.model = model
        self.retries = retries
        self.options = {key: value for key, value in {
            "reasoning_effort": reasoning_effort, "max_tokens": max_tokens,
        }.items() if value is not None}
        self.on_usage = on_usage
        self.calls = []
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self):
        self.client.close()

    def response_schema(self):
        return "hospitality_proposals", proposal_schema()

    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 on_usage=None) -> str:
        # The extractor can constrain a list-focused pass without changing pair matching.
        name, default_schema = self.response_schema()
        schema = schema if schema is not None else default_schema
        payload = {
            **self.options,
            "model": self.model, "messages": messages, "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": name, "strict": True, "schema": schema,
            }},
        }
        requests = 0

        def post():
            nonlocal requests
            requests += 1
            started = time.monotonic()
            def account(status, usage=None):
                values = {"attempt": requests, "status_code": status,
                          "wall_seconds": time.monotonic() - started,
                          "retries": requests - 1, **(usage or {})}
                self.calls.append(values)
                if self.on_usage:
                    self.on_usage(values)
                if on_usage:
                    on_usage(values)
            try:
                response = self.client.post("chat/completions", json=payload)
            except httpx.TransportError:
                account(None)
                raise
            usage = {}
            try:
                body = response.json()
                reported = body.get("usage") if isinstance(body, dict) else None
                if isinstance(reported, dict):
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = reported.get(key)
                        if type(value) is int and value >= 0:
                            usage[key] = value
                    if "total_tokens" not in usage and all(
                        key in usage for key in ("prompt_tokens", "completion_tokens")
                    ):
                        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
                    details = reported.get("completion_tokens_details") or {}
                    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
                    if type(reasoning) is int and reasoning >= 0:
                        usage["reasoning_tokens"] = reasoning
            except ValueError:
                pass
            account(response.status_code, usage)
            return response

        for attempt in range(self.retries + 1):
            try:
                response = post()
                # Older compatible endpoints may not implement structured output. The schema
                # remains in the system prompt and local validation is never relaxed.
                if response.status_code in {400, 422} and "response_format" in payload:
                    payload.pop("response_format")
                    response = post()
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
                time.sleep(min(2 ** attempt, 8))
                continue
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            response.raise_for_status()
            try:
                raw = response.json()["choices"][0]["message"]["content"]
                if isinstance(raw, list):
                    raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
                if not isinstance(raw, str):
                    raise TypeError
                return raw
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                raise ModelResponseError("model response has no text content") from exc
        raise RuntimeError("unreachable")
