import tomllib
from types import SimpleNamespace

def load_config(path: str = "config.toml") -> SimpleNamespace:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return SimpleNamespace(**{k: SimpleNamespace(**v) for k, v in raw.items()})