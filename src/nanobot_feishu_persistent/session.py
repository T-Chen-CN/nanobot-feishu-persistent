"""Session-scan helpers: extract breadcrumbs from nanobot session JSONL files.

A nanobot session file is JSONL where each non-metadata line looks roughly
like ``{"role": "...", "content": <str|list[block]>, "timestamp": "..."}``.
Feishu images leave a ``<feishu-images .../>`` breadcrumb inside the content.
This module locates the right file, walks it newest-first, and parses those
breadcrumbs into structured records so agents don't have to write regex.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .breadcrumb import Breadcrumb, parse_breadcrumbs


def sessions_dir() -> Path:
    return Path(
        os.path.expanduser(
            os.environ.get(
                "NBFP_SESSIONS_DIR",
                "~/.nanobot/workspace/sessions",
            )
        )
    )


def session_file_for_chat(chat_id: str, *, base: Path | None = None) -> Path:
    base = base or sessions_dir()
    return base / f"feishu_persistent_{chat_id}.jsonl"


@dataclass
class BreadcrumbHit:
    ids: list[str]
    message_id: str | None
    chat_id: str | None
    count: int | None
    received: str | None
    line: int
    role: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _iter_content_strings(content) -> Iterable[str]:
    """Yield every string that may carry a breadcrumb from a content value."""
    if content is None:
        return
    if isinstance(content, str):
        yield content
        return
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                yield block
            elif isinstance(block, dict):
                for key in ("text", "content", "value"):
                    v = block.get(key)
                    if isinstance(v, str):
                        yield v


def _parse_received_epoch(received: str | None) -> int | None:
    if not received:
        return None
    try:
        # Accept both trailing 'Z' and '+00:00'
        s = received.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    except (ValueError, TypeError):
        return None


def extract_from_session(
    path: str | Path,
    *,
    since_seconds: int | None = None,
    now_epoch: int | None = None,
) -> list[BreadcrumbHit]:
    """Return breadcrumb hits found in ``path``, newest-line first.

    ``since_seconds`` filters by the breadcrumb's ``received`` attribute when
    parseable; hits without a parseable timestamp are kept (fail-open).
    """
    p = Path(path).expanduser()
    hits: list[BreadcrumbHit] = []
    if not p.is_file():
        return hits

    cutoff: int | None
    if since_seconds is not None:
        import time as _t

        cutoff = (now_epoch or int(_t.time())) - since_seconds
    else:
        cutoff = None

    with p.open("r", encoding="utf-8") as f:
        for i, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            # skip pure metadata rows (session header)
            if obj.get("_type") and "content" not in obj and "role" not in obj:
                continue
            role = obj.get("role")
            content = obj.get("content")
            for s in _iter_content_strings(content):
                for bc in parse_breadcrumbs(s):
                    # Reject docs/self-references that lack real routing fields.
                    if not bc.ids or not bc.message_id:
                        continue
                    ts = _parse_received_epoch(bc.received)
                    if cutoff is not None and ts is not None and ts < cutoff:
                        continue
                    hits.append(
                        BreadcrumbHit(
                            ids=list(bc.ids),
                            message_id=bc.message_id,
                            chat_id=bc.chat_id,
                            count=bc.count,
                            received=bc.received,
                            line=i,
                            role=role,
                        )
                    )
    # newest-first
    hits.reverse()
    return hits


def collect_recent_ids(
    hits: list[BreadcrumbHit], *, limit: int
) -> list[str]:
    """Take the first ``limit`` hits (already newest-first) and flatten ids,
    preserving order and de-duplicating.
    """
    seen: set[str] = set()
    out: list[str] = []
    for h in hits[: max(limit, 0)]:
        for i in h.ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
    return out
