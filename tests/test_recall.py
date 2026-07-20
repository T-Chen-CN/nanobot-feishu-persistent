from pathlib import Path

from nanobot_feishu_persistent.index import Index
from nanobot_feishu_persistent.recall import recall_by_ids


def test_recall_with_refetch(tmp_path):
    db = tmp_path / "idx.db"
    img = tmp_path / "a.jpg"
    img.write_bytes(b"orig")
    with Index(db) as idx:
        rec = idx.upsert_from_file(img, message_id="om_1", image_key="img_1")
    img.unlink()  # simulate disk loss

    calls = {"n": 0}

    def fake_refetch(r):
        calls["n"] += 1
        assert r.message_id == "om_1"
        assert r.image_key == "img_1"
        return b"refetched-bytes"

    with Index(db) as idx:
        result = recall_by_ids(idx, [rec.image_id], auto_refetch=True, refetch=fake_refetch)

    assert calls["n"] == 1
    assert rec.image_id in result.refetched
    assert Path(rec.local_path).read_bytes() == b"refetched-bytes"
    assert result.missing_on_disk == []


def test_recall_refetch_skipped_without_keys(tmp_path):
    db = tmp_path / "idx.db"
    img = tmp_path / "a.jpg"
    img.write_bytes(b"orig")
    with Index(db) as idx:
        rec = idx.upsert_from_file(img)  # no message_id / image_key
    img.unlink()

    def should_not_be_called(r):
        raise AssertionError("refetch should be skipped without keys")

    with Index(db) as idx:
        result = recall_by_ids(
            idx, [rec.image_id], auto_refetch=True, refetch=should_not_be_called
        )

    assert rec.image_id in result.missing_on_disk
    assert result.refetched == []
