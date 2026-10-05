"""Configuration, loaded from environment variables (optionally a local .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PROJECT = ROOT / "sample_project"
DEMO_TASK = "Add validation so age cannot be negative and write a test for it."


@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    max_repair_attempts: int = 3
    max_explore_steps: int = 10
    test_timeout: int = 60
    llm_timeout: int = 90
    allow_custom_project: bool = False
    max_runs_per_session: int = 5

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def load_settings(**overrides) -> Settings:
    base = Settings(
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL") or Settings.model,
        base_url=(os.getenv("LLM_BASE_URL") or Settings.base_url).rstrip("/"),
        max_repair_attempts=min(_int_env("MAX_REPAIR_ATTEMPTS", 3), 3),
        test_timeout=_int_env("TEST_TIMEOUT", 60),
        allow_custom_project=os.getenv("ALLOW_CUSTOM_PROJECT", "false").lower() == "true",
        max_runs_per_session=max(_int_env("MAX_RUNS_PER_SESSION", 5), 1),
    )
    return replace(base, **{k: v for k, v in overrides.items() if v is not None})
