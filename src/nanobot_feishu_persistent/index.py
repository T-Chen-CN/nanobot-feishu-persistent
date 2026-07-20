"""SQLite-backed image index.

Schema is intentionally narrow — the plugin is the only writer, the CLI is the
only reader. All timestamps are unix seconds (int).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    image_id     TEXT PRIMARY KEY,
    chat_id      TEXT,
    sender_id    TEXT,
    message_id   TEXT,
    image_key    TEXT,
    local_path   TEXT NOT NULL,
    mime         TEXT,
    size_bytes   INTEGER,
    received_at  INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    session_id   TEXT,
    turn_id      TEXT,
    tags         TEXT NOT NULL DEFAULT '[]',
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_images_chat_time ON images(chat_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_images_message   ON images(message_id);
CREATE INDEX IF NOT EXISTS idx_images_key       ON images(image_key);
CREATE INDEX IF NOT EXISTS idx_images_sha       ON images(sha256);
"""


@dataclass
class ImageRecord:
    image_id: str
    local_path: str
    sha256: str
    received_at: int
    chat_id: str | None = None
    sender_id: str | None = None
    message_id: str | None = None
    image_key: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    session_id: str | None = None
    turn_id: str | None = None
    tags: list[str] = field(default_factory=list)
    note: str | None = None

    def to_dict(self, *, include_exists: bool = True) -> dict:
        d = asdict(self)
        if include_exists:
            try:
                d["exists"] = Path(self.local_path).is_file()
            except OSError:
                d["exists"] = False
        return d


def _row_to_record(row: sqlite3.Row) -> ImageRecord:
    return ImageRecord(
        image_id=row["image_id"],
        local_path=row["local_path"],
        sha256=row["sha256"],
        received_at=row["received_at"],
        chat_id=row["chat_id"],
        sender_id=row["sender_id"],
        message_id=row["message_id"],
        image_key=row["image_key"],
        mime=row["mime"],
        size_bytes=row["size_bytes"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        tags=json.loads(row["tags"] or "[]"),
        note=row["note"],
    )


def compute_sha256(path: str | Path, *, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def derive_image_id(sha256: str) -> str:
    return sha256[:12]


def _guess_mime(path: str | Path) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
    }.get(ext, "application/octet-stream")


class Index:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    # ---- lifecycle -----------------------------------------------------
    def open(self) -> "Index":
        if self._conn is not None:
            return self
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA)
        self._conn = conn
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Index":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    # ---- writes --------------------------------------------------------
    def upsert_from_file(
        self,
        local_path: str | Path,
        *,
        chat_id: str | None = None,
        sender_id: str | None = None,
        message_id: str | None = None,
        image_key: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        received_at: int | None = None,
        tags: Iterable[str] | None = None,
        note: str | None = None,
    ) -> ImageRecord:
        p = Path(local_path)
        if not p.is_file():
            raise FileNotFoundError(str(p))
        sha = compute_sha256(p)
        image_id = derive_image_id(sha)
        size = p.stat().st_size
        rec = ImageRecord(
            image_id=image_id,
            local_path=str(p.resolve()),
            sha256=sha,
            received_at=int(received_at if received_at is not None else time.time()),
            chat_id=chat_id,
            sender_id=sender_id,
            message_id=message_id,
            image_key=image_key,
            mime=_guess_mime(p),
            size_bytes=size,
            session_id=session_id,
            turn_id=turn_id,
            tags=list(tags or []),
            note=note,
        )
        self._upsert(rec)
        return rec

    def _upsert(self, rec: ImageRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO images (image_id, chat_id, sender_id, message_id, image_key,
                                local_path, mime, size_bytes, received_at, sha256,
                                session_id, turn_id, tags, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(image_id) DO UPDATE SET
                chat_id     = COALESCE(excluded.chat_id, images.chat_id),
                sender_id   = COALESCE(excluded.sender_id, images.sender_id),
                message_id  = COALESCE(excluded.message_id, images.message_id),
                image_key   = COALESCE(excluded.image_key, images.image_key),
                local_path  = excluded.local_path,
                mime        = COALESCE(excluded.mime, images.mime),
                size_bytes  = COALESCE(excluded.size_bytes, images.size_bytes),
                session_id  = COALESCE(excluded.session_id, images.session_id),
                turn_id     = COALESCE(excluded.turn_id, images.turn_id)
            """,
            (
                rec.image_id, rec.chat_id, rec.sender_id, rec.message_id, rec.image_key,
                rec.local_path, rec.mime, rec.size_bytes, rec.received_at, rec.sha256,
                rec.session_id, rec.turn_id, json.dumps(rec.tags, ensure_ascii=False), rec.note,
            ),
        )

    def add_tags(self, image_ids: Iterable[str], tags: Iterable[str]) -> int:
        tags = list(tags)
        n = 0
        for iid in image_ids:
            row = self.conn.execute("SELECT tags FROM images WHERE image_id = ?", (iid,)).fetchone()
            if not row:
                continue
            current = json.loads(row["tags"] or "[]")
            merged = sorted({*current, *tags})
            self.conn.execute("UPDATE images SET tags = ? WHERE image_id = ?",
                              (json.dumps(merged, ensure_ascii=False), iid))
            n += 1
        return n

    def set_note(self, image_id: str, note: str) -> bool:
        cur = self.conn.execute("UPDATE images SET note = ? WHERE image_id = ?", (note, image_id))
        return cur.rowcount > 0

    # ---- reads ---------------------------------------------------------
    def get_many(self, image_ids: Iterable[str]) -> list[ImageRecord]:
        ids = [i.strip() for i in image_ids if i and i.strip()]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM images WHERE image_id IN ({placeholders})", ids
        ).fetchall()
        by_id = {r["image_id"]: _row_to_record(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def by_message(self, message_id: str) -> list[ImageRecord]:
        rows = self.conn.execute(
            "SELECT * FROM images WHERE message_id = ? ORDER BY received_at ASC",
            (message_id,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def list_recent(
        self,
        chat_id: str | None = None,
        *,
        since_seconds: int | None = None,
        limit: int = 20,
        tags: Iterable[str] | None = None,
    ) -> list[ImageRecord]:
        clauses = []
        params: list = []
        if chat_id:
            clauses.append("chat_id = ?")
            params.append(chat_id)
        if since_seconds is not None:
            clauses.append("received_at >= ?")
            params.append(int(time.time()) - since_seconds)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM images {where} ORDER BY received_at DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        recs = [_row_to_record(r) for r in rows]
        if tags:
            wanted = set(tags)
            recs = [r for r in recs if wanted.issubset(set(r.tags))]
        return recs

    def iter_all(self) -> Iterator[ImageRecord]:
        for r in self.conn.execute("SELECT * FROM images ORDER BY received_at ASC"):
            yield _row_to_record(r)

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()
        return int(row["c"]) if row else 0


@contextmanager
def open_index(db_path: str | Path) -> Iterator[Index]:
    idx = Index(db_path).open()
    try:
        yield idx
    finally:
        idx.close()
