from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from agent_run import exit_codes
from agent_run.errors import AgentRunError

API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise AgentRunError(
                "OPENROUTER_API_KEY is not set",
                exit_codes.OPENROUTER_ERROR,
            )
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/local/agent-run",
                "X-Title": "agent-run",
            },
            timeout=120.0,
        )

    def close(self) -> None:
        self._client.close()

    def get_usage_usd(self) -> float:
        try:
            r = self._client.get("/key")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentRunError(f"OpenRouter usage poll failed: {exc}", exit_codes.OPENROUTER_ERROR) from exc
        data = r.json().get("data") or r.json()
        usage = data.get("usage")
        if usage is None:
            raise AgentRunError(f"Unexpected /key payload: {r.text[:500]}", exit_codes.OPENROUTER_ERROR)
        # usage may be total USD spent on the key
        return float(usage)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            body["response_format"] = response_format
        try:
            r = self._client.post("/chat/completions", json=body)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                detail = exc.response.text[:800]
            raise AgentRunError(
                f"OpenRouter chat failed: {exc} {detail}",
                exit_codes.OPENROUTER_ERROR,
            ) from exc
        payload = r.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentRunError(f"Bad chat response: {payload}", exit_codes.OPENROUTER_ERROR) from exc


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))
