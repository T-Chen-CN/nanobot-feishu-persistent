# Changelog

## 0.2.0 — 2026-07-20

### Added

- `nbfp recall recent --chat-id <ou_...> [--limit N] [--since 10m]` — one-shot
  agent recipe. Scans the Feishu session JSONL newest-first, extracts
  breadcrumbs, and returns the same envelope as `recall load`
  (`images[].local_path` ready for `read_file`). Also accepts `--session
  <path>` for explicit files.
- `nanobot_feishu_persistent.session` module exposing
  `extract_from_session()`, `collect_recent_ids()`,
  `session_file_for_chat()`, and a `BreadcrumbHit` dataclass.
- Session-dir override via `NBFP_SESSIONS_DIR` env var.
- Tests covering escaped-quote JSONL, multi-image lines, `--since` filtering,
  missing session files, and an end-to-end CLI happy path.

### Rationale

Before 0.2 the agent had to grep the session file for the breadcrumb XML
tag itself, which broke on JSON-escaped quotes and forced knowledge of the
nanobot session schema. `recent` collapses the whole recall path to one
CLI call.

## 0.1.0 — 2026-07-20

- Initial release: `FeishuPersistentChannel`, SQLite index at
  `~/.nanobot/plugins/feishu_persistent/index.db`, `nbfp recall`
  subcommands (`load`, `by-message`, `list`, `refetch`, `reindex`, `tag`,
  `annotate`, `doctor`), breadcrumb injection into inbound message text.
