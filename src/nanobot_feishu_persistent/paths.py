"""Runtime paths for the plugin (index, media, log)."""
from __future__ import annotations

import os
from pathlib import Path


def _env_or(default: str, env: str) -> Path:
    return Path(os.path.expanduser(os.environ.get(env, default)))


def index_path() -> Path:
    p = _env_or("~/.nanobot/plugins/feishu_persistent/index.db", "NBFP_INDEX_DB")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def media_dir() -> Path:
    p = _env_or("~/.nanobot/media/feishu", "NBFP_MEDIA_DIR")
    p.mkdir(parents=True, exist_ok=True)
    return p
