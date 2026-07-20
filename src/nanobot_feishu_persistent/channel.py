"""nanobot channel plugin: FeishuPersistentChannel.

Overrides `_handle_message` to upsert every inbound image into the SQLite
index and inject a `<feishu-images .../>` breadcrumb into the text content
before the message is forwarded to the agent bus.

Design notes:
- Inherits nanobot's built-in FeishuChannel unchanged; all download / SDK /
  reaction logic is reused.
- Registered via `entry_points("nanobot.channels")` under the key
  `feishu_persistent`, so it lives alongside the built-in `feishu` and is
  selected by nanobot config `channels.feishu_persistent.enabled = true`.
- The upstream nanobot.channels.feishu import is deferred to import time of
  this module so `nanobot-feishu-persistent` can be installed without a
  concrete nanobot version pin. If nanobot is missing, an ImportError is
  raised when nanobot itself tries to load the plugin — which is the correct
  failure mode.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

try:  # pragma: no cover — exercised only inside a real nanobot install
    from nanobot.channels.feishu import FeishuChannel  # type: ignore
except Exception as e:  # noqa: BLE001
    FeishuChannel = None  # type: ignore[assignment]
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None

from .breadcrumb import make_breadcrumb
from .index import Index
from .paths import index_path

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _iso_now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()


if FeishuChannel is not None:

    class FeishuPersistentChannel(FeishuChannel):  # type: ignore[misc, valid-type]
        """FeishuChannel + persistent image index + breadcrumb injection."""

        name = "feishu_persistent"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._nbfp_index: Index | None = None

        def _nbfp_get_index(self) -> Index:
            if self._nbfp_index is None:
                self._nbfp_index = Index(str(index_path())).open()
            return self._nbfp_index

        async def _handle_message(
            self,
            sender_id: str,
            chat_id: str,
            content: str,
            media: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
            session_key: str | None = None,
            is_dm: bool = False,
        ) -> None:
            enriched_content = content
            try:
                if media:
                    image_paths = [
                        m for m in media if Path(m).suffix.lower() in _IMAGE_EXTS
                    ]
                    if image_paths:
                        idx = self._nbfp_get_index()
                        message_id = (metadata or {}).get("message_id")
                        image_ids: list[str] = []
                        for path in image_paths:
                            try:
                                rec = idx.upsert_from_file(
                                    path,
                                    chat_id=chat_id,
                                    sender_id=sender_id,
                                    message_id=message_id,
                                    session_id=session_key,
                                )
                                image_ids.append(rec.image_id)
                            except FileNotFoundError:
                                # Media path recorded but file missing on disk;
                                # skip — upstream will still show the [image:] text.
                                continue
                        if image_ids:
                            crumb = make_breadcrumb(
                                image_ids,
                                message_id=message_id,
                                chat_id=chat_id,
                                received=_iso_now(),
                            )
                            enriched_content = (
                                f"{content}\n{crumb}" if content else crumb
                            )
            except Exception:  # noqa: BLE001 — never break message flow
                self.logger.exception("[nbfp] indexing failed")
                enriched_content = content

            await super()._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=enriched_content,
                media=media,
                metadata=metadata,
                session_key=session_key,
                is_dm=is_dm,
            )

else:  # pragma: no cover

    class FeishuPersistentChannel:  # type: ignore[no-redef]
        """Placeholder raised when nanobot is not installed."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "nanobot.channels.feishu is required for FeishuPersistentChannel: "
                f"{_IMPORT_ERROR!r}"
            )
