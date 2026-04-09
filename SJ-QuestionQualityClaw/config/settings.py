"""SJ-QuestionQualityClaw runtime configuration.

All tunable parameters in one place. Loaded from environment variables
with sensible defaults for local development.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ReviewConfig:
    """Review engine parameters."""

    default_passes: int = 3
    pass_threshold: float = 7.0
    revision_threshold: float = 5.0
    max_revision_cycles: int = 3
    batch_concurrency: int = 3
    temperature_base: float = 0.3
    temperature_spread: float = 0.15
    llm_timeout_seconds: float = 90.0
    llm_max_tokens: int = 4096


@dataclass
class GitHubConfig:
    """GitHub integration parameters."""

    token: str = field(
        default_factory=lambda: os.environ.get("GITHUB_TOKEN", "")
    )
    repo_owner: str = field(
        default_factory=lambda: os.environ.get("GITHUB_REPO_OWNER", "astrorekcah")
    )
    repo_name: str = field(
        default_factory=lambda: os.environ.get("GITHUB_REPO_NAME", "sj-question-bank")
    )
    base_branch: str = "main"


@dataclass
class LinearConfig:
    """Linear ticket management parameters."""

    api_key: str = field(default_factory=lambda: os.environ.get("LINEAR_API_KEY", ""))
    team_id: str = field(default_factory=lambda: os.environ.get("LINEAR_TEAM_ID", ""))


@dataclass
class LLMConfig:
    """LLM backend parameters."""

    backend: str = field(default_factory=lambda: os.environ.get("LLM_BACKEND", "openrouter"))
    model: str = field(
        default_factory=lambda: os.environ.get(
            "SELECTED_MODEL", "anthropic/claude-sonnet-4-20250514"
        )
    )
    api_key: str = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", ""))
    base_url: str = "https://openrouter.ai/api/v1"


@dataclass
class DatabaseConfig:
    """PostgreSQL connection parameters."""

    host: str = field(default_factory=lambda: os.environ.get("DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.environ.get("DB_PORT", "5432")))
    name: str = field(default_factory=lambda: os.environ.get("DB_NAME", "sjqqc_db"))
    user: str = field(default_factory=lambda: os.environ.get("DB_USER", "sjqqc"))
    password: str = field(default_factory=lambda: os.environ.get("DB_PASSWORD", "sjqqc"))

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass
class SJQQCConfig:
    """Top-level configuration."""

    review: ReviewConfig = field(default_factory=ReviewConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    linear: LinearConfig = field(default_factory=LinearConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)


DEFAULT_CONFIG = SJQQCConfig()
