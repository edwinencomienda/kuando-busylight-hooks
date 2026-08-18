# kuando-busylight-hooks

Shared controller for a kuando Busylight, driven by Claude Code, Codex, and Pi
hooks through the kuandoHUB local HTTP API (`http://localhost:8989`).

The full HTTP API reference (all actions, parameters, sound list, volume
values, multi-device addressing) lives in
[`docs/kuandoHUB Manual MacOS 2.0.0.pdf`](docs/kuandoHUB%20Manual%20MacOS%202.0.0.pdf)
— consult it for any future changes to how `kuando.py` talks to the API.

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
so Claude, Codex, and Pi can share the same light without fighting.

## Multi-agent awareness

Every session (Claude, Codex, or Pi) registers itself in `/tmp/kuando-agents.json`
(file-locked, keyed by the `session_id` each hook receives on stdin). The
light reflects the whole fleet:

- An agent finishes → **green + sound**, then back to **red** if any agent
  is still running, otherwise off.
- An agent needs attention → **orange + sound**, then back to **red** if any
  agent is still running, otherwise off.
- The green/orange window lasts **20s** normally, shortened to **10s** when
  other agents are still working, so the busy state returns sooner.
- Every timed state re-checks the fleet when it expires, so the light always
  settles on red (busy) or off (idle). Orange never auto-repeats — there is
  no hook event when a permission is *approved*, so a lingering "waiting"
  mark can't be trusted after its 20s window.
- A session ends or a permission is denied → that agent is deregistered;
  the light falls back to red (others running), orange (others waiting),
  or off (fleet idle).

Crash safety: registry entries expire after 6h, so a session that died
without firing `SessionEnd` can't hold the light red forever.

## Hook wiring

### Event → state mapping

| Event | State | Claude Code | Codex | Pi |
|---|---|---|---|---|
| `UserPromptSubmit` | `working` | ✅ | ✅ | ✅ (`agent_start`) |
| `Stop` | `done` | ✅ | ✅ | ✅ (`agent_end`) |
| `PermissionRequest` | `waiting` | ✅ | ✅ | ❌ (no permission-prompt event in Pi's extension API) |
| `PermissionDenied` | `off` | ✅ | ❌ (event not supported by Codex) | ❌ |
| `SessionEnd` | `off` | ✅ | ✅ | ✅ (`session_shutdown`) |

Note: interrupting a turn (Esc) has no dedicated event — Claude Code fires
`Stop` on interrupts too, so an interrupted turn shows the "done" state.

Note: `Notification` is deliberately NOT hooked — it fires for idle
reminders and other desktop-notification noise (e.g. what Ghostty surfaces),
which caused spurious orange states.

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

### Pi — `~/.pi/agent/extensions/kuando-busylight.ts`

Pi uses TypeScript extensions instead of JSON hooks. The extension listens
for `agent_start` / `agent_end` / `session_shutdown` and spawns `kuando.py`
with the matching state, piping `{"session_id": "pi-<session>"}` on stdin so
Pi sessions join the shared registry. There is no `waiting` state — Pi's
extension API has no permission-prompt event.

After editing, reload: Claude Code picks changes up via `/hooks` or a new
session; Codex and Pi need their sessions restarted.

All entries carry the `# kuando-busylight-hook` comment marker so they can be
found or bulk-rewritten later (grep for `kuando-busylight-hook`).

## Requirements

- kuandoHUB running with **HTTP Server** enabled (Advanced Settings) and the
  **HTTP** entry active in Platform Priorities.
- Python 3 (stdlib only).

## Tuning

Edit the constants at the top of `kuando.py`: colors, blink speed (`SLOW`),
sounds/volume, and `DISPLAY_SECONDS` / `DISPLAY_SECONDS_BUSY` (how long done/waiting stay lit; the busy value applies when other agents are still working).
