"""Shared LLM client with IronClaw backend + direct API fallback.

Primary: uses `ironclaw run -m` for LLM calls (Rust-native caching,
23 providers, cost tracking, prompt injection defense).

Fallback: direct OpenRouter API via httpx (when ironclaw is not available).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any

import httpx
from loguru import logger


def _ironclaw_available() -> bool:
    """Check if the ironclaw binary is installed."""
    return shutil.which("ironclaw") is not None


class LLMClient:
    """LLM client: IronClaw backend (primary) + direct API (fallback).

    When IronClaw is available, uses `ironclaw run -m` for LLM calls.
    This gives us Rust-native caching, 23 providers, cost tracking,
    and prompt injection defense for free.

    Falls back to direct OpenRouter API via httpx when IronClaw is
    not installed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        *,
        cache_enabled: bool = True,
        use_ironclaw: bool | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model or os.environ.get(
            "SELECTED_MODEL", "anthropic/claude-sonnet-4"
        )
        self.base_url = base_url or "https://openrouter.ai/api/v1"

        # Auto-detect IronClaw availability
        if use_ironclaw is None:
            self._use_ironclaw = _ironclaw_available()
        else:
            self._use_ironclaw = use_ironclaw

        if self._use_ironclaw:
            logger.info("LLM backend: IronClaw (Rust-native)")
        else:
            logger.info("LLM backend: direct API (httpx)")

        from sjqqc.cache import CostTracker, ResponseCache

        # Cache only needed for direct API (IronClaw caches natively)
        self.cache = (
            ResponseCache() if cache_enabled and not self._use_ironclaw
            else None
        )
        self.costs = CostTracker()

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

        Uses IronClaw when available (Rust-native caching + cost tracking).
        Falls back to direct API with Python caching.
        """
        if self._use_ironclaw:
            return await self._chat_ironclaw(system, user)
        return await self._chat_direct(
            system, user,
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=use_cache,
        )

    async def _chat_ironclaw(
        self, system: str, user: str
    ) -> dict[str, Any]:
        """Call IronClaw for LLM completion. IronClaw handles caching + costs."""
        # Combine system + user into a single prompt for ironclaw -m
        prompt = (
            f"SYSTEM: {system}\n\n"
            f"USER: {user}\n\n"
            "Respond with valid JSON only."
        )

        proc = await asyncio.create_subprocess_exec(
            "ironclaw", "run", "-m", prompt,
            "--no-db", "--cli-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "NO_COLOR": "1"},
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=120.0
        )

        if proc.returncode != 0:
            logger.warning(
                "IronClaw failed (rc={}), falling back to direct API",
                proc.returncode,
            )
            return await self._chat_direct(system, user)

        text = stdout.decode().strip()
        return self._extract_json_from_text(text)

    async def _chat_direct(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Direct OpenRouter API call with Python caching."""
        # Check cache first
        if use_cache and self.cache:
            cached = self.cache.get(self.model, system, user)
            if cached is not None:
                from sjqqc.cache import CallCost

                self.costs.add(CallCost(
                    model=self.model, cached=True,
                ))
                return cached

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

        # Track costs from usage data
        usage = raw.get("usage", {})
        if usage:
            from sjqqc.cache import estimate_cost

            cost = estimate_cost(
                self.model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
            self.costs.add(cost)

        result = self._extract_json(raw)

        # Cache the result
        if use_cache and self.cache:
            self.cache.put(self.model, system, user, result)

        return result

    @staticmethod
    def _extract_json(raw: dict[str, Any]) -> dict[str, Any]:
        """Extract JSON from OpenRouter API response."""
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected LLM response: {}", raw)
            raise ValueError("Could not extract LLM content") from exc
        return LLMClient._extract_json_from_text(content)

    @staticmethod
    def _extract_json_from_text(text: str) -> dict[str, Any]:
        """Extract JSON from any text (API response or IronClaw output)."""
        text = text.strip()

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
