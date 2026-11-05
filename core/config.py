"""Central settings loaded from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()

@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    fred_api_key: str
    finnhub_api_key: str
    claude_model: str
    db_path: Path
    cache_dir: Path
    checkpoint_path: Path
    
    def missing_keys(self) -> list[str]:
        required = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "FRED_API_KEY": self.fred_api_key,
            "FINNHUB_API_KEY": self.finnhub_api_key
        }
        return [name for name, value in required.items() if not value]
    
settings = Settings(
    anthropic_api_key=_env("ANTHROPIC_API_KEY"),
    fred_api_key=_env("FRED_API_KEY"),
    finnhub_api_key=_env("FINNHUB_API_KEY"),
    claude_model=_env("CLAUDE_MODEL") or "claude-haiku-5-5",
    db_path=ROOT / "app.db",
    cache_dir=ROOT / ".cache",
    checkpoint_path=ROOT / "checkpoints.db",
)