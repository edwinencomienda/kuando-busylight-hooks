# kuando-busylight-hooks

Shared controller for a kuando Busylight, driven by Claude Code and Codex hooks
through the kuandoHUB local HTTP API (`http://localhost:8989`).

## States

| Command | Light | Sound |
|---|---|---|
| `kuando.py working` | blinking red (fast) | — |
| `kuando.py done` | blinking green (slow) for 20s, then off | Kuando Train (3) at 25% |
| `kuando.py waiting` | blinking orange (slow) for 20s, then off | Quiet (5) at 25% |
| `kuando.py off` | off immediately | — |

All HTTP calls fail silently (2s timeout) if kuandoHUB isn't running.
Timed shutoffs run in a detached child process guarded by a nonce in
`/tmp/kuando-claude-state` — any newer state cancels older pending timers,
so Claude and Codex can share the same light without fighting.

## Hook wiring

### Event → state mapping

| Event | State | Claude Code | Codex |
|---|---|---|---|
| `UserPromptSubmit` | `working` | ✅ | ✅ |
| `Stop` | `done` | ✅ | ✅ |
| `Notification` | `waiting` | ✅ | ✅ |
| `PermissionRequest` | `waiting` | ✅ | ✅ |
| `PermissionDenied` | `off` | ✅ | ❌ (event not supported by Codex) |

### Claude Code — `~/.claude/settings.json`

Add one entry per event above under `hooks.<Event>`, changing only the state
argument (`working` / `done` / `waiting` / `off`):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/edwinencomienda/Code/Personal/kuando-busylight-hooks/kuando.py working 2>/dev/null || true # kuando-busylight-hook",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### Codex — `~/.codex/hooks.json`

Same schema and same command entries, under the same event names (minus
`PermissionDenied`). Do **not** set `"async": true` — Codex rejects async
hooks; the script backgrounds its own timed work so it isn't needed.

After editing, reload: Claude Code picks changes up via `/hooks` or a new
session; Codex needs its sessions restarted.

All entries carry the `# kuando-busylight-hook` comment marker so they can be
found or bulk-rewritten later (grep for `kuando-busylight-hook`).

## Requirements

- kuandoHUB running with **HTTP Server** enabled (Advanced Settings) and the
  **HTTP** entry active in Platform Priorities.
- Python 3 (stdlib only).

## Tuning

Edit the constants at the top of `kuando.py`: colors, blink speed (`SLOW`),
sounds/volume, and `DISPLAY_SECONDS` (how long done/waiting stay lit).
