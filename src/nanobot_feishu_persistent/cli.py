"""`nbfp` command-line entry point.

Contract: every subcommand prints one JSON object to stdout when --json is
set (default). Exit codes:
    0 all-success
    1 argparse / usage error (argparse default)
    2 partial success (some ids missing, some refetched, etc.)
    3 total failure
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .index import Index
from .paths import index_path, media_dir
from .recall import recall_by_ids, recall_by_message, reindex_dir, RecallResult


def _emit(obj: dict, *, as_json: bool) -> None:
    if as_json:
        json.dump(obj, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        # Human-readable fallback: compact one-per-line summary.
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _exit_from_result(res: RecallResult) -> int:
    if not res.images and res.errors:
        return 3
    if res.missing_on_disk or res.errors:
        return 2
    return 0


def _parse_since(spec: str | None) -> int | None:
    if not spec:
        return None
    s = spec.strip().lower()
    mult = 1
    if s.endswith("h"):
        mult, s = 3600, s[:-1]
    elif s.endswith("m"):
        mult, s = 60, s[:-1]
    elif s.endswith("d"):
        mult, s = 86400, s[:-1]
    elif s.endswith("s"):
        mult, s = 1, s[:-1]
    return int(float(s) * mult)


def _open_index(args) -> Index:
    db = args.db or str(index_path())
    return Index(db).open()


# ---------- subcommand handlers -----------------------------------------
def cmd_load(args) -> int:
    ids = [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    with _open_index(args) as idx:
        # Refetch callback is None in CLI mode; the plugin channel wires in a
        # real Feishu client-backed refetch in its own path.
        result = recall_by_ids(idx, ids, auto_refetch=args.auto_refetch)
    _emit(result.to_dict(), as_json=args.json)
    return _exit_from_result(result)


def cmd_by_message(args) -> int:
    with _open_index(args) as idx:
        result = recall_by_message(idx, args.message_id, auto_refetch=args.auto_refetch)
    _emit(result.to_dict(), as_json=args.json)
    return _exit_from_result(result)


def cmd_list(args) -> int:
    since = _parse_since(args.since)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
    with _open_index(args) as idx:
        recs = idx.list_recent(
            chat_id=args.chat_id,
            since_seconds=since,
            limit=args.limit,
            tags=tags,
        )
    payload = {
        "ok": True,
        "images": [r.to_dict() for r in recs],
        "count": len(recs),
    }
    _emit(payload, as_json=args.json)
    return 0


def cmd_refetch(args) -> int:
    ids = [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    with _open_index(args) as idx:
        # CLI has no live Feishu client. Report which records are candidates.
        recs = idx.get_many(ids)
        candidates = [r for r in recs if r.message_id and r.image_key]
        payload = {
            "ok": False,
            "note": "CLI cannot refetch without a live Feishu client. "
                    "Use the channel plugin's refetch path, or wire a client "
                    "via a future --app-config flag.",
            "candidates": [r.to_dict() for r in candidates],
            "not_refetchable": [
                r.image_id for r in recs if not (r.message_id and r.image_key)
            ],
        }
    _emit(payload, as_json=args.json)
    return 2


def cmd_reindex(args) -> int:
    since = _parse_since(args.since)
    scan = args.dir or str(media_dir())
    with _open_index(args) as idx:
        report = reindex_dir(idx, scan, since_seconds=since)
    _emit(report, as_json=args.json)
    return 0 if report.get("ok") else 2


def cmd_tag(args) -> int:
    ids = [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    tags = [t.strip() for t in (args.add or "").split(",") if t.strip()]
    with _open_index(args) as idx:
        n = idx.add_tags(ids, tags)
    _emit({"ok": True, "updated": n, "tags": tags}, as_json=args.json)
    return 0


def cmd_annotate(args) -> int:
    with _open_index(args) as idx:
        ok = idx.set_note(args.id, args.note)
    _emit({"ok": ok, "id": args.id}, as_json=args.json)
    return 0 if ok else 2


def cmd_doctor(args) -> int:
    scan = args.dir or str(media_dir())
    with _open_index(args) as idx:
        total = idx.count()
        # Orphans on disk (files not in index)
        indexed_paths = {r.local_path for r in idx.iter_all()}
        orphans_disk: list[str] = []
        p = Path(scan).expanduser()
        if p.is_dir():
            for f in p.iterdir():
                if f.is_file() and str(f.resolve()) not in indexed_paths:
                    orphans_disk.append(str(f.resolve()))
        # Orphans in index (record exists but file gone)
        orphans_index: list[str] = []
        for rec in idx.iter_all():
            if not Path(rec.local_path).is_file():
                orphans_index.append(rec.image_id)
    _emit(
        {
            "ok": not (orphans_disk or orphans_index),
            "db": str(args.db or index_path()),
            "media_dir": scan,
            "total_indexed": total,
            "orphans_on_disk": orphans_disk,
            "orphans_in_index": orphans_index,
            "timestamp": int(time.time()),
        },
        as_json=args.json,
    )
    return 0


# ---------- parser -------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nbfp",
        description="nanobot-feishu-persistent CLI (index + recall for Feishu images)",
    )
    p.add_argument("--version", action="version", version=f"nbfp {__version__}")

    top = p.add_subparsers(dest="group", required=True)
    recall = top.add_parser("recall", help="Query the persistent image index")
    sub = recall.add_subparsers(dest="cmd", required=True)

    def _common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--db", help="SQLite index path (default: $NBFP_INDEX_DB or ~/.nanobot/plugins/feishu_persistent/index.db)")
        sp.add_argument("--json", action="store_true", default=True,
                        help="Emit JSON (default; kept for explicitness)")
        sp.add_argument("--no-json", dest="json", action="store_false",
                        help="Pretty-print instead of single-line JSON")

    sp = sub.add_parser("load", help="Load image records by ids")
    _common(sp)
    sp.add_argument("--ids", required=True, help="Comma-separated image ids from breadcrumb")
    sp.add_argument("--auto-refetch", action="store_true",
                    help="Attempt Feishu API refetch when the local file is missing")
    sp.set_defaults(func=cmd_load)

    sp = sub.add_parser("by-message", help="Load images tied to a Feishu message_id")
    _common(sp)
    sp.add_argument("--message-id", required=True)
    sp.add_argument("--auto-refetch", action="store_true")
    sp.set_defaults(func=cmd_by_message)

    sp = sub.add_parser("list", help="List recent images")
    _common(sp)
    sp.add_argument("--chat-id")
    sp.add_argument("--since", default="24h", help="Time window, e.g. 30m, 24h, 7d")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--tags", help="Comma-separated tag filter (AND)")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("refetch", help="(Advisory) list refetch candidates")
    _common(sp)
    sp.add_argument("--ids", required=True)
    sp.set_defaults(func=cmd_refetch)

    sp = sub.add_parser("reindex", help="Scan media dir and upsert records")
    _common(sp)
    sp.add_argument("--dir", help="Media dir to scan (default: ~/.nanobot/media/feishu)")
    sp.add_argument("--since", help="Only files modified within this window")
    sp.set_defaults(func=cmd_reindex)

    sp = sub.add_parser("tag", help="Add tags to image records")
    _common(sp)
    sp.add_argument("--ids", required=True)
    sp.add_argument("--add", required=True, help="Comma-separated tags")
    sp.set_defaults(func=cmd_tag)

    sp = sub.add_parser("annotate", help="Attach a note to one image record")
    _common(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", required=True)
    sp.set_defaults(func=cmd_annotate)

    sp = sub.add_parser("doctor", help="Report index / disk drift")
    _common(sp)
    sp.add_argument("--dir")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except FileNotFoundError as e:
        _emit({"ok": False, "error": str(e)}, as_json=getattr(args, "json", True))
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
