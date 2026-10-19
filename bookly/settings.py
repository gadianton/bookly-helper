import os
import tomllib
from pathlib import Path


def load_settings() -> dict:
    return tomllib.loads((Path(__file__).parent / "settings.toml").read_text())


def require_anthropic_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit("Set ANTHROPIC_API_KEY first: export ANTHROPIC_API_KEY=...")
