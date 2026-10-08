import tomllib
from pathlib import Path


def load_settings() -> dict:
    return tomllib.loads((Path(__file__).parent / "settings.toml").read_text())
