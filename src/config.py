"""Application configuration: pydantic-settings loads from environment variables and .env files (ARCHITECTURE §7).

The env_file path is overridable via the ``CALC_AGENT_ENV_FILE`` environment variable (default ``.env``);
setting it to ``/dev/null`` bypasses .env entirely (the basis for key-less acceptance).
In M0 the key fields may be empty; presence is not validated.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE: str = os.environ.get("CALC_AGENT_ENV_FILE", ".env")


class Settings(BaseSettings):
    """Global configuration (fields correspond one-to-one with .env.example)."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "gpt-4o"
    calc_agent_max_steps: int = 25
    http_allowed_hosts: str = "example.com"
    data_sandbox_dir: str = "data"
    # SEARCH_EXHAUSTED framework capability parameter (contract §4.2; unconsumed in Phase A, consumed by Phase B sequence constraints)
    experiment_max_search_attempts: int = 100

    @property
    def allowed_hosts(self) -> list[str]:
        """Parse the comma-separated host allow-list into a list."""
        return [host.strip() for host in self.http_allowed_hosts.split(",") if host.strip()]


def get_settings() -> Settings:
    """Construct a Settings instance (works in a key-less environment, M0-3 basis)."""
    return Settings()
