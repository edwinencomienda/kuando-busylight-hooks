#!/usr/bin/env python3
"""Kuando Busylight controller for Claude Code / Codex hooks.

Talks to the kuandoHUB local HTTP API (http://localhost:8989).
Every call fails silently if kuandoHUB isn't running, and returns
immediately — timed follow-ups (re-blink, lights-off) run in a
detached background process guarded by a shared state file, so a
newer state always cancels older pending timers.

Usage: kuando.py {working|done|waiting|off}
  working  blinking red (agent is working)
  done     jingle + slow blinking green for 20s, then off
  waiting  jingle + slow blinking orange for 20s, then off
  off      lights off immediately
"""
import os
import subprocess
import sys
import time
import urllib.request

BASE = "http://localhost:8989"
STATE_FILE = "/tmp/kuando-claude-state"
TIMEOUT = 2  # seconds per HTTP request

GREEN = "green=100"
RED = "red=100"
ORANGE = "red=100&green=40"
SLOW = "ontime=7&offtime=7"  # 0.7s on / 0.7s off
DONE_SOUND = "sound=3&volume=25"     # Kuando Train
WAITING_SOUND = "sound=5&volume=25"  # Quiet
DISPLAY_SECONDS = 20  # how long done/waiting states stay lit
JINGLE_SECONDS = 3    # solid-color window while the jingle plays


def call(query: str) -> None:
    """Send one GET command; never raise."""
    try:
        urllib.request.urlopen(f"{BASE}?{query}", timeout=TIMEOUT).read()
    except Exception:
        pass


def write_state() -> str:
    nonce = str(time.time_ns())
    try:
        with open(STATE_FILE, "w") as f:
            f.write(nonce)
    except OSError:
        pass
    return nonce


def state_is(nonce: str) -> bool:
    try:
        with open(STATE_FILE) as f:
            return f.read() == nonce
    except OSError:
        return False


def spawn_delayed(nonce: str, color: str) -> None:
    """Detach a child that re-blinks after the jingle and shuts off later."""
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_delayed", nonce, color],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_delayed(nonce: str, color: str) -> None:
    time.sleep(JINGLE_SECONDS)
    if state_is(nonce):
        call(f"action=blink&{color}&{SLOW}")
    time.sleep(DISPLAY_SECONDS - JINGLE_SECONDS)
    if state_is(nonce):
        call("action=light&red=0&green=0&blue=0")


def timed_state(color: str, sound: str) -> None:
    nonce = write_state()
    call(f"action=blink&{color}&{SLOW}")
    call(f"action=jingle&{color}&{sound}")
    spawn_delayed(nonce, color)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "working":
        write_state()
        call(f"action=blink&{RED}")
    elif cmd == "done":
        timed_state(GREEN, DONE_SOUND)
    elif cmd == "waiting":
        timed_state(ORANGE, WAITING_SOUND)
    elif cmd == "off":
        write_state()
        call("action=light&red=0&green=0&blue=0")
    elif cmd == "_delayed" and len(sys.argv) == 4:
        run_delayed(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
