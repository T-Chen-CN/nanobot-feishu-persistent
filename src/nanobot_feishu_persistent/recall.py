"""Recall: given ids, return image records with a 3-tier fallback.

Tier 1: SQLite lookup + on-disk file present.
Tier 2: File missing but message_id+image_key present -> Feishu API refetch.
Tier 3: Neither present -> record marked missing.

The Feishu refetch is delegated to a callback so the CLI (which has no live
channel context) can inject a client factory. If no callback is provided,
refetch tier is skipped and the record is reported missing_on_disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .index import Index, ImageRecord

RefetchFn = Callable[[ImageRecord], bytes | None]


@dataclass
class RecallResult:
    images: list[ImageRecord] = field(default_factory=list)
    missing_on_disk: list[str] = field(default_factory=list)
    refetched: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": not self.errors and not self.missing_on_disk,
            "images": [r.to_dict() for r in self.images],
            "missing_on_disk": list(self.missing_on_disk),
            "refetched": list(self.refetched),
            "errors": list(self.errors),
        }


def _try_refetch(rec: ImageRecord, refetch: RefetchFn | None) -> bool:
    if refetch is None or not rec.message_id or not rec.image_key:
        return False
    try:
        data = refetch(rec)
    except Exception as e:  # noqa: BLE001
        return False
    if not data:
        return False
    try:
        p = Path(rec.local_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return True
    except OSError:
        return False


def recall_by_ids(
    index: Index,
    ids: Iterable[str],
    *,
    auto_refetch: bool = False,
    refetch: RefetchFn | None = None,
) -> RecallResult:
    result = RecallResult()
    ids = list(ids)
    records = index.get_many(ids)
    found_ids = {r.image_id for r in records}
    for missing_id in [i for i in ids if i not in found_ids]:
        result.errors.append({"id": missing_id, "error": "not_in_index"})

    for rec in records:
        exists = Path(rec.local_path).is_file()
        if not exists and auto_refetch and _try_refetch(rec, refetch):
            result.refetched.append(rec.image_id)
            exists = True
        if not exists:
            result.missing_on_disk.append(rec.image_id)
        result.images.append(rec)
    return result


def recall_by_message(index: Index, message_id: str, **kwargs) -> RecallResult:
    recs = index.by_message(message_id)
    ids = [r.image_id for r in recs]
    return recall_by_ids(index, ids, **kwargs)


def reindex_dir(
    index: Index,
    scan_dir: str | Path,
    *,
    since_seconds: int | None = None,
) -> dict:
    import time

    scan = Path(scan_dir).expanduser()
    cutoff = int(time.time()) - since_seconds if since_seconds else 0
    scanned = 0
    added = 0
    updated = 0
    errors: list[dict] = []
    if not scan.is_dir():
        return {"ok": False, "scan_dir": str(scan), "scanned": 0, "added": 0,
                "updated": 0, "errors": [{"error": "scan_dir_missing"}]}
    for p in scan.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            continue
        try:
            mtime = int(p.stat().st_mtime)
        except OSError as e:
            errors.append({"path": str(p), "error": str(e)})
            continue
        if mtime < cutoff:
            continue
        scanned += 1
        try:
            existed = index.conn.execute(
                "SELECT 1 FROM images WHERE local_path = ?", (str(p.resolve()),)
            ).fetchone()
            index.upsert_from_file(p, received_at=mtime)
            if existed:
                updated += 1
            else:
                added += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"path": str(p), "error": str(e)})
    return {
        "ok": not errors,
        "scan_dir": str(scan),
        "scanned": scanned,
        "added": added,
        "updated": updated,
        "errors": errors,
    }
