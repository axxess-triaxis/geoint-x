from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEOINTX_", env_file=(REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    pack_dir: Path = REPO_ROOT / "data" / "demo_pack"
    var_dir: Path = REPO_ROOT / "var"
    db_url: str | None = None
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    # Download missing demo-pack rasters from the GitHub release on first use.
    pack_autofetch: bool = False

    # GenAI (optional). Without a key the system uses deterministic templates.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_s: float = 45.0
    ai_enabled: bool = True

    @property
    def artifact_dir(self) -> Path:
        return self.var_dir / "artifacts"

    @property
    def upload_dir(self) -> Path:
        return self.var_dir / "uploads"

    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        self.var_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.var_dir / 'geointx.db').as_posix()}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    import os

    s = Settings()
    # Also accept the conventional GEMINI_API_KEY name.
    if not s.gemini_api_key and os.environ.get("GEMINI_API_KEY"):
        s.gemini_api_key = os.environ["GEMINI_API_KEY"]
    return s
