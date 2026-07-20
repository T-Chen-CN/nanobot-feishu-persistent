from pathlib import Path

from nanobot_feishu_persistent.index import Index, compute_sha256, derive_image_id


def _make_img(tmp_path: Path, name: str, content: bytes = b"\x89PNG\r\n\x1a\nfake") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_index_upsert_and_get_many(tmp_path):
    img = _make_img(tmp_path, "a.jpg", b"hello")
    db = tmp_path / "idx.db"
    with Index(db) as idx:
        rec = idx.upsert_from_file(
            img,
            chat_id="c1",
            sender_id="u1",
            message_id="om_1",
            image_key="img_1",
        )
        assert rec.image_id == derive_image_id(compute_sha256(img))
        assert rec.size_bytes == 5
        assert rec.chat_id == "c1"

        again = idx.upsert_from_file(img, chat_id="c1")
        assert again.image_id == rec.image_id

        got = idx.get_many([rec.image_id, "missing_id"])
        assert len(got) == 1
        assert got[0].image_id == rec.image_id


def test_by_message_and_list_recent(tmp_path):
    db = tmp_path / "idx.db"
    with Index(db) as idx:
        r1 = idx.upsert_from_file(_make_img(tmp_path, "a.jpg", b"a"), chat_id="c1", message_id="om_1")
        r2 = idx.upsert_from_file(_make_img(tmp_path, "b.jpg", b"b"), chat_id="c1", message_id="om_1")
        r3 = idx.upsert_from_file(_make_img(tmp_path, "c.jpg", b"c"), chat_id="c2", message_id="om_2")

        by_msg = idx.by_message("om_1")
        assert {r.image_id for r in by_msg} == {r1.image_id, r2.image_id}

        recent_c1 = idx.list_recent(chat_id="c1", limit=10)
        assert {r.image_id for r in recent_c1} == {r1.image_id, r2.image_id}

        assert idx.count() == 3


def test_tags_and_notes(tmp_path):
    db = tmp_path / "idx.db"
    with Index(db) as idx:
        rec = idx.upsert_from_file(_make_img(tmp_path, "a.jpg", b"x"))
        assert idx.add_tags([rec.image_id], ["listing", "front"]) == 1
        assert idx.set_note(rec.image_id, "silver body") is True
        got = idx.get_many([rec.image_id])[0]
        assert set(got.tags) == {"listing", "front"}
        assert got.note == "silver body"
