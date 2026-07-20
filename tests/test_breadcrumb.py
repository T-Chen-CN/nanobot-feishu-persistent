from nanobot_feishu_persistent.breadcrumb import make_breadcrumb, parse_breadcrumbs


def test_render_and_parse_roundtrip():
    s = make_breadcrumb(
        ["a1", "a2", "a3"],
        message_id="om_x",
        chat_id="ou_y",
        received="2026-07-20T18:11:23Z",
    )
    assert '<feishu-images ' in s and s.endswith("/>")
    parsed = parse_breadcrumbs(f"hello world\n{s}\ntail")
    assert len(parsed) == 1
    b = parsed[0]
    assert b.ids == ["a1", "a2", "a3"]
    assert b.message_id == "om_x"
    assert b.chat_id == "ou_y"
    assert b.count == 3
    assert b.received == "2026-07-20T18:11:23Z"


def test_parse_multiple():
    text = (
        'top <feishu-images ids="a,b" count="2"/> mid '
        '<feishu-images ids="c" message_id="om_2"/> end'
    )
    out = parse_breadcrumbs(text)
    assert [b.ids for b in out] == [["a", "b"], ["c"]]


def test_parse_no_match():
    assert parse_breadcrumbs("nothing to see") == []
    assert parse_breadcrumbs("") == []
