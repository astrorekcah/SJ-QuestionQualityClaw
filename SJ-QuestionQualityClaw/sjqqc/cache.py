"""LLM response cache with TTL eviction + cost tracking.

Inspired by IronClaw's response_cache.rs — caches LLM responses keyed
by SHA-256 hash of system+user prompt + model. Identical requests skip
the API entirely. Tool-calling/mutation requests should NOT be cached.

Also tracks per-call token costs for budget visibility.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

# Per-model costs (input, output) per 1K tokens — from OpenRouter pricing
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-4": (0.003, 0.015),
    "anthropic/claude-sonnet-4.5": (0.003, 0.015),
    "anthropic/claude-sonnet-4.6": (0.003, 0.015),
    "anthropic/claude-3.7-sonnet": (0.003, 0.015),
    "anthropic/claude-3.5-sonnet": (0.003, 0.015),
    "openai/gpt-4o": (0.0025, 0.01),
    "openai/gpt-4o-mini": (0.00015, 0.0006),
}

DEFAULT_COST = (0.003, 0.015)  # conservative default


@dataclass
class CallCost:
    """Cost of a single LLM call."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    cached: bool = False

    @property
    def total_cost_usd(self) -> float:
        return self.input_cost_usd + self.output_cost_usd


@dataclass
class CostTracker:
    """Aggregate cost tracker across a session."""

    calls: list[CallCost] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def cached_calls(self) -> int:
        return sum(1 for c in self.calls if c.cached)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.total_cost_usd for c in self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def savings_from_cache(self) -> float:
        """Estimated cost saved by cache hits."""
        return sum(
            c.total_cost_usd for c in self.calls if c.cached
        )

    def add(self, call: CallCost) -> None:
        self.calls.append(call)

    def log_summary(self) -> None:
        logger.info(
            "Cost: ${:.4f} | {} calls ({} cached) | "
            "{} input + {} output tokens",
            self.total_cost_usd,
            self.total_calls,
            self.cached_calls,
            self.total_input_tokens,
            self.total_output_tokens,
        )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> CallCost:
    """Estimate the cost of an LLM call."""
    input_rate, output_rate = MODEL_COSTS.get(model, DEFAULT_COST)
    return CallCost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_tokens / 1000 * input_rate,
        output_cost_usd=output_tokens / 1000 * output_rate,
    )


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    response: dict[str, Any]
    created_at: float
    hit_count: int = 0


class ResponseCache:
    """In-memory LLM response cache with TTL and max-size eviction.

    Keyed by SHA-256 of (model + system prompt + user prompt).
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_entries: int = 500,
    ) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._cache: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def _key(self, model: str, system: str, user: str) -> str:
        h = hashlib.sha256()
        h.update(model.encode())
        h.update(system.encode())
        h.update(user.encode())
        return h.hexdigest()

    def get(self, model: str, system: str, user: str) -> dict[str, Any] | None:
        """Look up a cached response. Returns None on miss."""
        key = self._key(model, system, user)
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        # Check TTL
        if time.time() - entry.created_at > self.ttl:
            del self._cache[key]
            self._misses += 1
            return None

        entry.hit_count += 1
        self._hits += 1

        if (self._hits + self._misses) % 50 == 0:
            total = self._hits + self._misses
            rate = self._hits / total if total else 0
            logger.debug(
                "Cache: {}/{} hits ({:.0%}), {} entries",
                self._hits, total, rate, len(self._cache),
            )

        return entry.response

    def put(self, model: str, system: str, user: str, response: dict[str, Any]) -> None:
        """Store a response in the cache."""
        # Evict oldest if at capacity
        if len(self._cache) >= self.max_entries:
            oldest_key = min(
                self._cache, key=lambda k: self._cache[k].created_at
            )
            del self._cache[oldest_key]

        key = self._key(model, system, user)
        self._cache[key] = CacheEntry(
            response=response,
            created_at=time.time(),
        )

    @property
    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total else 0,
            "entries": len(self._cache),
        }
