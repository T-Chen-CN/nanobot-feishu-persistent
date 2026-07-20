"""Tests for the session-scan / `nbfp recall recent` path."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nanobot_feishu_persistent.index import Index
from nanobot_feishu_persistent.session import (
    collect_recent_ids,
    extract_from_session,
    session_file_for_chat,
)


def _line(role: str, content, ts: str) -> str:
    return json.dumps({"role": role, "content": content, "timestamp": ts}) + "\n"


def _bc(ids: str, mid: str, chat: str, received: str, count: int = 1) -> str:
    return (
        f'<feishu-images ids="{ids}" message_id="{mid}" '
        f'chat_id="{chat}" count="{count}" received="{received}"/>'
    )


def test_extract_parses_escaped_and_multi(tmp_path: Path):
    session = tmp_path / "feishu_persistent_ou_abc.jsonl"
    session.write_text(
        # metadata header (should be skipped)
        json.dumps({"_type": "session", "key": "x", "created_at": "t"}) + "\n"
        # plain assistant line, no image
        + _line("assistant", "hello", "2026-07-20T20:00:00")
        # user text carrying two breadcrumbs in one message
        + _line(
            "user",
            "[image: /a.jpg]\n"
            + _bc("id_a", "om_1", "ou_abc", "2026-07-20T20:10:00+00:00")
            + "\n[image: /b.jpg]\n"
            + _bc("id_b1,id_b2", "om_2", "ou_abc", "2026-07-20T20:20:00+00:00", 2),
            "2026-07-20T20:20:00",
        )
        # newer breadcrumb — should come first
        + _line(
            "user",
            _bc("id_c", "om_3", "ou_abc", "2026-07-20T20:30:00+00:00"),
            "2026-07-20T20:30:00",
        )
    )

    hits = extract_from_session(session)
    assert [h.ids for h in hits] == [["id_c"], ["id_b1", "id_b2"], ["id_a"]]
    assert hits[0].message_id == "om_3"
    assert hits[1].count == 2
    assert all(h.role == "user" for h in hits)


def test_collect_recent_ids_respects_limit(tmp_path: Path):
    session = tmp_path / "s.jsonl"
    now = datetime.now(timezone.utc)
    lines = []
    for i in range(3):
        ts = (now - timedelta(minutes=(3 - i))).isoformat()
        lines.append(_line("user", _bc(f"id_{i}", f"om_{i}", "ou_x", ts), ts))
    session.write_text("".join(lines))

    hits = extract_from_session(session)
    # newest-first
    assert [h.ids[0] for h in hits] == ["id_2", "id_1", "id_0"]
    assert collect_recent_ids(hits, limit=1) == ["id_2"]
    assert collect_recent_ids(hits, limit=2) == ["id_2", "id_1"]


def test_since_filter(tmp_path: Path):
    session = tmp_path / "s.jsonl"
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    old = now - timedelta(hours=2)
    fresh = now - timedelta(minutes=5)
    session.write_text(
        _line("user", _bc("old_id", "om_o", "ou_x", old.isoformat()),
              old.isoformat())
        + _line("user", _bc("new_id", "om_n", "ou_x", fresh.isoformat()),
                fresh.isoformat())
    )

    hits = extract_from_session(
        session, since_seconds=15 * 60, now_epoch=int(now.timestamp())
    )
    assert [h.ids[0] for h in hits] == ["new_id"]


def test_session_file_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NBFP_SESSIONS_DIR", str(tmp_path))
    from importlib import reload

    from nanobot_feishu_persistent import session as sess_mod

    reload(sess_mod)
    p = sess_mod.session_file_for_chat("ou_xyz")
    assert p == tmp_path / "feishu_persistent_ou_xyz.jsonl"


def _cli(env_home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(env_home),
        "NBFP_INDEX_DB": str(env_home / "index.db"),
        "NBFP_MEDIA_DIR": str(env_home / "media"),
        "NBFP_SESSIONS_DIR": str(env_home / "sessions"),
    }
    return subprocess.run(
        [sys.executable, "-m", "nanobot_feishu_persistent.cli", "recall", *args],
        env=env,
        capture_output=True,
        text=True,
    )


def test_recent_cli_end_to_end(tmp_path: Path):
    # arrange: media file, session breadcrumb, index record
    (tmp_path / "sessions").mkdir()
    (tmp_path / "media").mkdir()
    img = tmp_path / "media" / "img_v3_test.jpg"
    img.write_bytes(b"jpegbytes")

    with Index(tmp_path / "index.db") as idx:
        rec = idx.upsert_from_file(
            img,
            message_id="om_msg_1",
            image_key="img_key_1",
            chat_id="ou_xyz",
        )

    now = datetime.now(timezone.utc).isoformat()
    session = tmp_path / "sessions" / "feishu_persistent_ou_xyz.jsonl"
    session.write_text(
        _line(
            "user",
            f"[image: {img}]\n"
            + _bc(rec.image_id, "om_msg_1", "ou_xyz", now),
            now,
        )
    )

    res = _cli(tmp_path, "recent", "--chat-id", "ou_xyz", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["images"][0]["local_path"] == str(img.resolve())
    assert payload["breadcrumbs"][0]["ids"] == [rec.image_id]


def test_recent_cli_missing_session_file(tmp_path: Path):
    (tmp_path / "sessions").mkdir()
    res = _cli(tmp_path, "recent", "--chat-id", "ou_missing", "--json")
    assert res.returncode == 3
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["errors"][0]["error"] == "session_file_not_found"
