#!/usr/bin/env python3
"""Kuando Busylight controller for Claude Code / Codex hooks.

Talks to the kuandoHUB local HTTP API (http://localhost:8989).
Every call fails silently if kuandoHUB isn't running, and returns
immediately — timed follow-ups run in a detached background process.

Multi-agent aware: every session (Claude or Codex) is registered in a
shared JSON registry keyed by the hook's session_id (read from stdin).
The light reflects the whole fleet, not just the last event:

  - any agent running            -> blinking red
  - an agent needs attention     -> blinking orange + sound for 20s,
                                    then back to red if others still run,
                                    otherwise off
  - an agent finishes            -> if others still run: stay red;
                                    if it was the last one: green + sound
                                    for 20s, then off

Usage: kuando.py {working|done|waiting|off}
Hook input (JSON with session_id) is read from stdin when present.
"""
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = "http://localhost:8989"
STATE_FILE = "/tmp/kuando-claude-state"     # nonce: newest light state wins
REGISTRY_FILE = "/tmp/kuando-agents.json"   # {session_id: {status, ts}}
TIMEOUT = 2          # seconds per HTTP request
AGENT_TTL = 6 * 3600  # drop registry entries older than this (crash safety)

GREEN = "green=100"
RED = "red=100"
ORANGE = "red=100&green=40"
SLOW = "ontime=7&offtime=7"  # 0.7s on / 0.7s off
DONE_SOUND = "sound=3&volume=25"     # Kuando Train
WAITING_SOUND = "sound=5&volume=25"  # Quiet
DISPLAY_SECONDS = 20       # how long done/waiting states stay lit
DISPLAY_SECONDS_BUSY = 10  # shorter window when other agents are still working
JINGLE_SECONDS = 3    # solid-color window while the jingle plays


# ---------- HTTP ----------

def call(query: str) -> None:
    """Send one GET command; never raise."""
    try:
        urllib.request.urlopen(f"{BASE}?{query}", timeout=TIMEOUT).read()
    except Exception:
        pass


def light_red() -> None:
    call(f"action=blink&{RED}")


def light_orange() -> None:
    call(f"action=blink&{ORANGE}&{SLOW}")


def light_green() -> None:
    call(f"action=blink&{GREEN}&{SLOW}")


def light_off() -> None:
    call("action=light&red=0&green=0&blue=0")


# ---------- nonce (newest light state wins) ----------

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


# ---------- agent registry ----------

def _locked_registry(mutate):
    """Load registry under an exclusive lock, apply mutate(reg), save."""
    try:
        fd = os.open(REGISTRY_FILE, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        return {}
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            raw = os.read(fd, 1 << 20).decode() or "{}"
            reg = json.loads(raw)
        except Exception:
            reg = {}
        now = time.time()
        reg = {k: v for k, v in reg.items()
               if now - v.get("ts", 0) < AGENT_TTL}
        mutate(reg)
        data = json.dumps(reg).encode()
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, data)
        return reg
    finally:
        os.close(fd)


def set_agent(session_id: str, status: str) -> dict:
    def mutate(reg):
        reg[session_id] = {"status": status, "ts": time.time()}
    return _locked_registry(mutate)


def remove_agent(session_id: str) -> dict:
    def mutate(reg):
        reg.pop(session_id, None)
    return _locked_registry(mutate)


def snapshot() -> dict:
    return _locked_registry(lambda reg: None)


def any_running(reg: dict) -> bool:
    return any(v.get("status") == "running" for v in reg.values())


def read_session_id() -> str:
    """Session id from the hook's stdin JSON; falls back to parent pid."""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw:
                sid = json.loads(raw).get("session_id")
                if sid:
                    return str(sid)
    except Exception:
        pass
    return f"pid-{os.getppid()}"


# ---------- delayed follow-ups (detached) ----------

def spawn_delayed(kind: str, nonce: str, seconds: int) -> None:
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_delayed", kind, nonce,
         str(seconds)],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_delayed(kind: str, nonce: str, seconds: int) -> None:
    color = light_green if kind == "done" else light_orange
    time.sleep(JINGLE_SECONDS)
    if state_is(nonce):
        color()  # restore blinking after the jingle's solid color
    time.sleep(max(seconds - JINGLE_SECONDS, 0))
    if not state_is(nonce):
        return  # a newer state took over; leave it alone
    reg = snapshot()
    write_state()
    if any_running(reg):
        light_red()
    else:
        light_off()


# ---------- states ----------

def cmd_working(sid: str) -> None:
    set_agent(sid, "running")
    write_state()
    light_red()


def display_seconds(reg: dict) -> int:
    """Shorter window when other agents are still working."""
    return DISPLAY_SECONDS_BUSY if any_running(reg) else DISPLAY_SECONDS


def cmd_waiting(sid: str) -> None:
    reg = set_agent(sid, "waiting")
    nonce = write_state()
    light_orange()
    call(f"action=jingle&{ORANGE}&{WAITING_SOUND}")
    spawn_delayed("waiting", nonce, display_seconds(reg))


def cmd_done(sid: str) -> None:
    reg = remove_agent(sid)
    nonce = write_state()
    light_green()
    call(f"action=jingle&{GREEN}&{DONE_SOUND}")
    # after the window: red if fleet busy, else off
    spawn_delayed("done", nonce, display_seconds(reg))


def cmd_off(sid: str) -> None:
    reg = remove_agent(sid)
    write_state()
    if any_running(reg):
        light_red()
    else:
        light_off()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "_delayed" and len(sys.argv) == 5:
        run_delayed(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        return
    if cmd not in ("working", "done", "waiting", "off"):
        print(__doc__)
        sys.exit(1)
    sid = read_session_id()
    {"working": cmd_working, "done": cmd_done,
     "waiting": cmd_waiting, "off": cmd_off}[cmd](sid)


if __name__ == "__main__":
    main()
