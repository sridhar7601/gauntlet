"""Central configuration, loaded from environment (.env) with safe defaults.

Nothing here reads provider API keys directly — those live inside Bifrost.
Gauntlet only needs the Bifrost base URL + a virtual key, and the Tavily key
for the web tool used inside agents.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bifrost_base_url: str = os.getenv("BIFROST_BASE_URL", "http://127.0.0.1:8080/v1")
    bifrost_virtual_key: str = os.getenv("BIFROST_VIRTUAL_KEY", "sk-bf-REPLACE_ME")
    model: str = os.getenv("GAUNTLET_MODEL", "openai/gpt-4o-mini")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key) and not self.tavily_api_key.endswith("REPLACE_ME")

    @property
    def has_virtual_key(self) -> bool:
        return bool(self.bifrost_virtual_key) and not self.bifrost_virtual_key.endswith("REPLACE_ME")


settings = Settings()
