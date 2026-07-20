"""Breadcrumb: `<feishu-images ids="..." .../>` inline marker.

Goal: a plain-text token that survives nanobot's persistence sanitizer, so a
later turn can grep it out of session history and hand the ids to `nbfp recall`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

_TAG_RE = re.compile(
    r'<feishu-images\b(?P<attrs>[^>]*?)/>',
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r'(?P<name>[a-zA-Z_][\w-]*)\s*=\s*"(?P<value>[^"]*)"')


@dataclass
class Breadcrumb:
    ids: list[str] = field(default_factory=list)
    message_id: str | None = None
    chat_id: str | None = None
    count: int | None = None
    received: str | None = None

    def render(self) -> str:
        parts = [f'ids="{",".join(self.ids)}"']
        if self.message_id:
            parts.append(f'message_id="{self.message_id}"')
        if self.chat_id:
            parts.append(f'chat_id="{self.chat_id}"')
        if self.count is not None:
            parts.append(f'count="{self.count}"')
        if self.received:
            parts.append(f'received="{self.received}"')
        return "<feishu-images " + " ".join(parts) + "/>"


def make_breadcrumb(
    image_ids: Iterable[str],
    *,
    message_id: str | None = None,
    chat_id: str | None = None,
    received: str | None = None,
) -> str:
    ids = [i for i in image_ids if i]
    return Breadcrumb(
        ids=ids,
        message_id=message_id,
        chat_id=chat_id,
        count=len(ids),
        received=received,
    ).render()


def parse_breadcrumbs(text: str) -> list[Breadcrumb]:
    out: list[Breadcrumb] = []
    if not text:
        return out
    for match in _TAG_RE.finditer(text):
        attrs = dict(_ATTR_RE.findall(match.group("attrs")))
        ids_raw = attrs.get("ids", "")
        ids = [x.strip() for x in ids_raw.split(",") if x.strip()]
        count_str = attrs.get("count")
        try:
            count = int(count_str) if count_str else None
        except ValueError:
            count = None
        out.append(
            Breadcrumb(
                ids=ids,
                message_id=attrs.get("message_id"),
                chat_id=attrs.get("chat_id"),
                count=count,
                received=attrs.get("received"),
            )
        )
    return out
