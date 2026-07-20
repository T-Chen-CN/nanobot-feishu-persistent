import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from nanobot_feishu_persistent.cli import main
from nanobot_feishu_persistent.index import Index


def _mk(tmp_path: Path, name: str, data: bytes = b"x") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _run(argv, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, json.loads(buf.getvalue())


def test_cli_load_and_list(tmp_path):
    db = tmp_path / "idx.db"
    img_a = _mk(tmp_path, "a.jpg", b"aa")
    img_b = _mk(tmp_path, "b.jpg", b"bb")
    with Index(db) as idx:
        ra = idx.upsert_from_file(img_a, chat_id="c1", message_id="om_1")
        rb = idx.upsert_from_file(img_b, chat_id="c1", message_id="om_1")

    code, out = _run(
        ["recall", "load", "--db", str(db), "--ids", f"{ra.image_id},{rb.image_id}"],
        tmp_path,
    )
    assert code == 0
    assert out["ok"] is True
    assert len(out["images"]) == 2
    assert all(r["exists"] for r in out["images"])

    code, out = _run(
        ["recall", "list", "--db", str(db), "--chat-id", "c1", "--since", "1h", "--limit", "5"],
        tmp_path,
    )
    assert code == 0
    assert out["count"] == 2


def test_cli_load_missing_id(tmp_path):
    db = tmp_path / "idx.db"
    with Index(db):
        pass
    code, out = _run(
        ["recall", "load", "--db", str(db), "--ids", "deadbeef"],
        tmp_path,
    )
    assert code == 3
    assert out["ok"] is False
    assert out["errors"][0]["error"] == "not_in_index"


def test_cli_load_missing_file(tmp_path):
    db = tmp_path / "idx.db"
    img = _mk(tmp_path, "a.jpg", b"aa")
    with Index(db) as idx:
        rec = idx.upsert_from_file(img, chat_id="c1")
    img.unlink()
    code, out = _run(
        ["recall", "load", "--db", str(db), "--ids", rec.image_id],
        tmp_path,
    )
    assert code == 2
    assert rec.image_id in out["missing_on_disk"]


def test_cli_reindex(tmp_path):
    scan = tmp_path / "media"
    scan.mkdir()
    _mk(scan, "one.jpg", b"111")
    _mk(scan, "two.png", b"222")
    _mk(scan, "note.txt", b"skip me")
    db = tmp_path / "idx.db"
    code, out = _run(
        ["recall", "reindex", "--db", str(db), "--dir", str(scan)],
        tmp_path,
    )
    assert code == 0
    assert out["scanned"] == 2
    assert out["added"] == 2


def test_cli_by_message_and_tag(tmp_path):
    db = tmp_path / "idx.db"
    img = _mk(tmp_path, "a.jpg", b"aa")
    with Index(db) as idx:
        rec = idx.upsert_from_file(img, chat_id="c1", message_id="om_9")

    code, out = _run(
        ["recall", "tag", "--db", str(db), "--ids", rec.image_id, "--add", "listing,front"],
        tmp_path,
    )
    assert code == 0 and out["updated"] == 1

    code, out = _run(
        ["recall", "by-message", "--db", str(db), "--message-id", "om_9"],
        tmp_path,
    )
    assert code == 0
    assert set(out["images"][0]["tags"]) == {"listing", "front"}
