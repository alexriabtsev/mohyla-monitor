"""Load and validate config/sources.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "docs"

REQUIRED_KEYS = ("user_agent", "lookback_hours", "digest_size", "relevance_patterns",
                 "categories", "weights")


class ConfigError(ValueError):
    pass


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"config {path} must be a mapping")
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ConfigError(f"config {path} missing keys: {', '.join(missing)}")
    return cfg
