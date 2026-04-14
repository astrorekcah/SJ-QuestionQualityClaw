"""LLM client for OpenRouter API with response caching and cost tracking.

Single backend: direct OpenRouter API via httpx. Clean, fast, reliable.
Caching and cost tracking built in.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from loguru import logger

# Max feedback length to prevent prompt injection via massive payloads
MAX_PROMPT_LENGTH = 50_000

# Simple rate limiter: max calls per minute
MAX_CALLS_PER_MINUTE = 30


def sanitize_prompt_input(text: str) -> str:
    """Sanitize user-provided text before embedding in LLM prompts.

    Strips control characters and truncates to prevent prompt injection
    via oversized payloads.
    """
    # Remove null bytes and control chars (keep newlines/tabs)
    cleaned = "".join(
        c for c in text
        if c == "\n" or c == "\t" or (ord(c) >= 32)
    )
    # Truncate
    if len(cleaned) > MAX_PROMPT_LENGTH:
        cleaned = cleaned[:MAX_PROMPT_LENGTH] + "\n[TRUNCATED]"
        logger.warning(
            "Prompt input truncated from {} to {} chars",
            len(text), MAX_PROMPT_LENGTH,
        )
    return cleaned


class LLMClient:
    """OpenRouter chat client with caching, cost tracking, and safety guards."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        *,
        cache_enabled: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model or os.environ.get(
            "SELECTED_MODEL", "anthropic/claude-sonnet-4"
        )
        self.base_url = base_url or "https://openrouter.ai/api/v1"

        # Validate API key
        if not self.api_key or self.api_key.startswith("{{"):
            logger.warning(
                "OPENROUTER_API_KEY not set — LLM calls will fail"
            )

        from sjqqc.cache import CostTracker, ResponseCache

        self.cache = ResponseCache() if cache_enabled else None
        self.costs = CostTracker()
        self._call_timestamps: list[float] = []

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Send a chat completion and return parsed JSON.

        Responses are cached by default (keyed by model+system+user).
        Set use_cache=False for mutation operations.
        """
        # Validate API key
        if not self.api_key or self.api_key.startswith("{{"):
            raise RuntimeError(
                "OPENROUTER_API_KEY not configured. "
                "Set it in .env or pass api_key to LLMClient."
            )

        # Rate limit
        self._enforce_rate_limit()

        # Check cache
        if use_cache and self.cache:
            cached = self.cache.get(self.model, system, user)
            if cached is not None:
                from sjqqc.cache import CallCost

                self.costs.add(CallCost(model=self.model, cached=True))
                return cached

        # Call API
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()

        # Track costs
        usage = raw.get("usage", {})
        if usage:
            from sjqqc.cache import estimate_cost

            self.costs.add(estimate_cost(
                self.model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            ))

        result = self._extract_json(raw)

        # Store in cache
        if use_cache and self.cache:
            self.cache.put(self.model, system, user, result)

        return result

    def _enforce_rate_limit(self) -> None:
        """Simple sliding-window rate limiter."""
        import time

        now = time.time()
        # Remove timestamps older than 60s
        self._call_timestamps = [
            t for t in self._call_timestamps if now - t < 60
        ]
        if len(self._call_timestamps) >= MAX_CALLS_PER_MINUTE:
            logger.warning(
                "Rate limit: {} calls in last 60s (max {})",
                len(self._call_timestamps), MAX_CALLS_PER_MINUTE,
            )
            raise RuntimeError(
                f"Rate limit exceeded: {MAX_CALLS_PER_MINUTE} calls/min"
            )
        self._call_timestamps.append(now)

    @staticmethod
    def _extract_json(raw: dict[str, Any]) -> dict[str, Any]:
        """Extract JSON from API response with fallback parsing."""
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected LLM response: {}", raw)
            raise ValueError("Could not extract LLM content") from exc

        text = content.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [
                ln for ln in lines
                if not ln.strip().startswith("```")
            ]
            text = "\n".join(lines).strip()

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback: find first { ... } block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.error("LLM response not valid JSON: {}", text[:500])
        raise ValueError("LLM response not valid JSON")
