# nanobot-feishu-persistent

Persistent, recallable Feishu image history for [nanobot](https://github.com/openclaw/nanobot).

Solves the cross-turn vision loss problem where nanobot's session sanitizer
strips `image_url` blocks on persistence, leaving only `[image: /path]` text
placeholders. This plugin keeps its own SQLite index of every inbound Feishu
image and drops a plain-text breadcrumb into the message so a later turn can
call the `nbfp` CLI to reload images from disk (with Feishu-API refetch as
fallback) and hand them back into vision through `read_file`.

## What it ships

1. `FeishuPersistentChannel` — a channel plugin that extends the built-in
   `nanobot.channels.feishu.FeishuChannel`. Registered under the entry-point
   name `feishu_persistent` so it lives alongside the built-in `feishu`.
2. `nbfp` — a CLI that owns the recall side (index reads, disk/API fallback,
   tagging, doctor).
3. A SQLite index at `~/.nanobot/plugins/feishu_persistent/index.db`
   (overridable via `NBFP_INDEX_DB`).
4. Breadcrumbs of the form
   `<feishu-images ids="..." message_id="..." chat_id="..." count="N" received="..."/>`
   injected into inbound message text — the sanitizer preserves them because
   they're plain text.

## Install

```bash
uv tool install --force git+https://github.com/T-Chen-CN/nanobot-feishu-persistent
# or, into the nanobot venv:
/home/you/.nanobot/venv/bin/pip install \
    git+https://github.com/T-Chen-CN/nanobot-feishu-persistent
```

Then in `~/.nanobot/config.json`:

```json
{
  "channels": {
    "feishu": { "enabled": false },
    "feishu_persistent": {
      "enabled": true,
      "appId": "cli_xxxxx",
      "appSecret": "xxxxx"
    }
  }
}
```

Restart the gateway.

## CLI

```
nbfp recall recent     --chat-id ou_xxx [--limit 1] [--since 10m]
nbfp recall load       --ids a,b,c [--auto-refetch]
nbfp recall by-message --message-id om_xxx
nbfp recall list       --chat-id ou_xxx --since 24h --limit 20
nbfp recall refetch    --ids a,b
nbfp recall reindex    [--dir DIR] [--since 7d]
nbfp recall tag        --ids a,b --add listing,front
nbfp recall annotate   --id a --note "silver body"
nbfp recall doctor
```

Every subcommand emits JSON to stdout. Exit codes: `0` all-success,
`2` partial success, `3` total failure, `1` argparse/usage error.

### JSON output contract

```json
{
  "ok": true,
  "images": [
    {
      "image_id": "a1b2c3d4e5f6",
      "local_path": "/home/.../img_v3_xxx.jpg",
      "exists": true,
      "message_id": "om_xxx",
      "image_key": "img_v3_xxx",
      "chat_id": "ou_xxx",
      "received_at": 1727819483,
      "size_bytes": 453120,
      "mime": "image/jpeg",
      "sha256": "...",
      "tags": ["listing", "front"],
      "note": null
    }
  ],
  "missing_on_disk": [],
  "refetched": [],
  "errors": []
}
```

## Agent usage pattern

The one-liner (v0.2+): the agent reads `Chat ID` from Runtime Context and runs

```
nbfp recall recent --chat-id $CHAT_ID --json
```

which scans `~/.nanobot/workspace/sessions/feishu_persistent_<chat_id>.jsonl`
newest-first, pulls the latest breadcrumb, loads its images (auto-refetching
from Feishu if missing on disk), and returns the same envelope as
`recall load`. The agent then `read_file`s each `local_path` to bring the
image back into vision.

Advanced: when an agent knows a specific breadcrumb from history and needs
a subset of images:

1. `nbfp recall load --ids <csv> --auto-refetch`
2. Parse `images[].local_path` from stdout JSON
3. `read_file` each needed path — nanobot's helper turns them into image blocks
   that the LLM can actually see for the current turn.

See `AGENTS.md` in your workspace for the exact convention.

## Design notes

- **No core patches.** The plugin only overrides `_handle_message`. nanobot
  upgrades don't invalidate it.
- **No MCP dependency.** Pure CLI + entry-point plugin. Agents invoke via
  their existing `exec` tool.
- **Storage is plugin-owned.** SQLite at `~/.nanobot/plugins/feishu_persistent/`.
  The nanobot session store is untouched.
- **Refetch is opt-in.** The CLI cannot refetch by itself (no live client);
  channel-side refetch will land in a later minor version.

## License

MIT
