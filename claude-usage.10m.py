#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Usage Monitor — SwiftBar Plugin
Shows Session, Weekly, and Extra usage limits as colored bars.

Color encodes pacing: green = ahead of pace, yellow = watch it, red = burning fast.
Pacing considers BOTH remaining capacity AND time until reset.

Refresh: every 10 minutes (per filename convention).
Data source: ~/.config/claude-menubar/usage.json
History log: ~/.config/claude-menubar/history.jsonl
"""

# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>

import json
import struct
import zlib
import base64
import colorsys
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONFIG_DIR = Path.home() / ".config" / "claude-menubar"
USAGE_FILE = CONFIG_DIR / "usage.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.jsonl"

# Resolve symlink so paths don't contain spaces (SwiftBar splits on spaces)
SCRIPT_DIR = Path(__file__).resolve().parent
UPDATER = SCRIPT_DIR / "update-usage.py"
PYTHON = "/opt/homebrew/bin/python3"

# Bar geometry (logical pixels — doubled for Retina)
# Menu bar icon is 22pt tall. We generate a 22px-tall image with bars
# centered vertically so SwiftBar doesn't auto-scale it.
ICON_H = 22      # match menu bar height — no scaling needed
BAR_W = 3
BAR_H = 11       # bar content height
GAP = 2
PAD_X = 1        # horizontal padding
CORNER_R = 1

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pacing & Color
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def pace_score(remaining_pct: float, time_remaining_pct: float) -> float:
    """
    Returns 0.0 (red/danger) → 1.0 (green/comfortable).
    Factors in both remaining capacity and time until reset.
    """
    r = max(0.0, min(100.0, remaining_pct))
    t = max(0.0, min(100.0, time_remaining_pct))

    if r <= 3:
        return 0.0
    if r >= 92:
        return 1.0
    if t <= 5:
        return min(1.0, r / 35.0)

    pace = r / max(t, 0.1)
    return min(1.0, max(0.0, pace / 1.3))


def score_to_rgb(score: float) -> tuple[int, int, int, int]:
    """Score 0→1 mapped through HSV: red(0°) → yellow(60°) → green(120°)."""
    hue = score * (120.0 / 360.0)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.78, 0.88)
    return (int(r * 255), int(g * 255), int(b * 255), 230)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pure-Python PNG generator (no Pillow needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    c = chunk_type + data
    crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return struct.pack(">I", len(data)) + c + crc


def create_png(width: int, height: int, pixels: list[list[tuple]]) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            r, g, b, a = pixels[y][x]
            raw += struct.pack("BBBB", r, g, b, a)
    compressed = zlib.compress(raw, 9)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def draw_rounded_rect(pixels, x0, y0, x1, y1, r, color):
    """Draw a filled rounded rectangle onto the pixel buffer."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            draw = True
            if x < x0 + r and y < y0 + r:
                if (x - (x0 + r)) ** 2 + (y - (y0 + r)) ** 2 > r * r:
                    draw = False
            elif x > x1 - r and y < y0 + r:
                if (x - (x1 - r)) ** 2 + (y - (y0 + r)) ** 2 > r * r:
                    draw = False
            elif x < x0 + r and y > y1 - r:
                if (x - (x0 + r)) ** 2 + (y - (y1 - r)) ** 2 > r * r:
                    draw = False
            elif x > x1 - r and y > y1 - r:
                if (x - (x1 - r)) ** 2 + (y - (y1 - r)) ** 2 > r * r:
                    draw = False
            if draw:
                sr, sg, sb, sa = color
                dr, dg, db, da = pixels[y][x]
                a = sa / 255.0
                pixels[y][x] = (
                    int(sr * a + dr * (1 - a)),
                    int(sg * a + dg * (1 - a)),
                    int(sb * a + db * (1 - a)),
                    min(255, sa + da),
                )


def generate_bars_image(bars: list[dict]) -> str:
    n = len(bars)
    W = PAD_X * 2 + BAR_W * n + GAP * (n - 1)
    H = ICON_H  # full menu-bar height — bars centered, no auto-scaling
    pixels = [[(0, 0, 0, 0) for _ in range(W)] for _ in range(H)]
    x = PAD_X
    bw = BAR_W
    bh = BAR_H
    y_top = (H - bh) // 2  # vertically center bars
    cr = CORNER_R
    for bar in bars:
        rpct = bar.get("remaining_pct", 100)
        tpct = bar.get("time_remaining_pct", 100)
        draw_rounded_rect(pixels, x, y_top, x + bw - 1, y_top + bh - 1, cr, (140, 140, 140, 45))
        fill_h = max(2, int(bh * max(0, min(100, rpct)) / 100.0))
        y_fill = y_top + bh - fill_h
        score = pace_score(rpct, tpct)
        color = score_to_rgb(score)
        draw_rounded_rect(pixels, x, y_fill, x + bw - 1, y_top + bh - 1, cr, color)
        x += BAR_W + GAP
    return base64.b64encode(create_png(W, H, pixels)).decode("ascii")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Time helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def time_remaining_str(reset_at_str: str) -> str:
    dt = parse_dt(reset_at_str)
    if not dt:
        return "—"
    now = datetime.now(timezone.utc)
    secs = (dt - now).total_seconds()
    if secs <= 0:
        return "now"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    if h > 48:
        return f"{h // 24}d"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def time_remaining_pct(reset_at_str: str, window_hours: float) -> float:
    dt = parse_dt(reset_at_str)
    if not dt or window_hours <= 0:
        return 50.0
    now = datetime.now(timezone.utc)
    secs_left = (dt - now).total_seconds()
    window_secs = window_hours * 3600
    return max(0.0, min(100.0, (secs_left / window_secs) * 100.0))


def format_ago(iso_str: str) -> str:
    """Human-readable 'last updated X ago' string."""
    dt = parse_dt(iso_str)
    if not dt:
        return "never"
    now = datetime.now(timezone.utc)
    secs = (now - dt).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 60:
        return "just now"
    m = int(secs // 60)
    if m < 60:
        return f"{m}m ago"
    h = int(m // 60)
    if h < 24:
        return f"{h}h {m % 60}m ago"
    return f"{h // 24}d ago"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Data loading & history log
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_usage() -> dict:
    """Load usage.json, computing derived fields."""
    if not USAGE_FILE.exists():
        return _placeholder()
    try:
        with open(USAGE_FILE) as f:
            data = json.load(f)
    except Exception:
        return _placeholder()

    for key in ("session", "weekly", "extra"):
        tier = data.get(key, {})
        if "time_remaining_pct" not in tier and "reset_at" in tier:
            window = tier.get("window_hours", {"session": 5, "weekly": 168, "extra": 720}.get(key, 5))
            tier["time_remaining_pct"] = time_remaining_pct(tier["reset_at"], window)
        if "remaining_pct" not in tier and "used" in tier and "limit" in tier:
            limit = tier["limit"]
            if limit > 0:
                tier["remaining_pct"] = max(0, (1 - tier["used"] / limit)) * 100
        data[key] = tier
    return data


def _placeholder() -> dict:
    return {
        "session": {"remaining_pct": -1, "time_remaining_pct": 50, "reset_at": ""},
        "weekly": {"remaining_pct": -1, "time_remaining_pct": 50, "reset_at": ""},
        "extra": {"remaining_pct": -1, "time_remaining_pct": 50, "reset_at": ""},
        "updated_at": "",
    }


def is_placeholder(data: dict) -> bool:
    return data.get("session", {}).get("remaining_pct", -1) < 0


def append_history(data: dict):
    """Append current snapshot to history.jsonl."""
    if is_placeholder(data):
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": {k: v for k, v in data.get("session", {}).items() if k in ("remaining_pct", "time_remaining_pct", "used", "limit")},
            "weekly": {k: v for k, v in data.get("weekly", {}).items() if k in ("remaining_pct", "time_remaining_pct", "used", "limit")},
            "extra": {k: v for k, v in data.get("extra", {}).items() if k in ("remaining_pct", "time_remaining_pct", "spent", "cap")},
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def try_background_update():
    """Fire-and-forget: scrape usage via Claude CLI /usage command."""
    try:
        scraper = SCRIPT_DIR / "scrape-usage-claude.sh"
        if scraper.exists():
            subprocess.Popen(
                ["/bin/bash", str(scraper)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SwiftBar output
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# SwiftBar: color=light_mode,dark_mode — force readable text in both themes
STYLE = "color=#000000,#ffffff size=13"
HINT_STYLE = "color=#000000,#ffffff size=12"


def pace_dot(score: float) -> str:
    if score >= 0.8:
        return "🟢"
    elif score >= 0.5:
        return "🟡"
    elif score >= 0.25:
        return "🟠"
    else:
        return "🔴"


def pace_label(score: float) -> str:
    if score >= 0.8:
        return "On pace"
    elif score >= 0.5:
        return "Burning fast"
    elif score >= 0.25:
        return "Slow down"
    else:
        return "⚠️ Near limit"


def format_tier_line(label: str, tier: dict) -> str:
    rpct = tier.get("remaining_pct", -1)
    tpct = tier.get("time_remaining_pct", 50)
    reset = time_remaining_str(tier.get("reset_at", ""))

    if rpct < 0:
        return f"⚪  {label}:  No data | {STYLE}"

    score = pace_score(rpct, tpct)
    dot = pace_dot(score)
    pace = pace_label(score)

    if "spent" in tier and "cap" in tier:
        remaining = max(0, tier["cap"] - tier["spent"])
        return f"{dot}  {label}:  ${remaining:.2f} / ${tier['cap']:.2f}  ·  {pace}  ·  resets {reset} | {STYLE}"

    return f"{dot}  {label}:  {rpct:.0f}%  ·  {pace}  ·  resets {reset} | {STYLE}"


def main():
    # Background poll: try to fetch fresh data for next cycle
    try_background_update()

    # Load cached data and log it
    data = load_usage()
    append_history(data)

    s = data.get("session", {})
    w = data.get("weekly", {})
    e = data.get("extra", {})

    # ── Menu bar icon ──
    if is_placeholder(data):
        print("🦊⚡ | sfimage=chart.bar.fill")
    else:
        print(f"| image={generate_bars_image([s, w, e])}")

    # ── Dropdown ──
    print("---")

    if is_placeholder(data):
        print(f"⚡ Claude Usage | {STYLE}")
        print("---")
        print(f"No usage data yet. | {STYLE}")
        print(f"Run update-usage.py or see README. | {STYLE}")
        print("---")
    else:
        # Header with last-updated
        ago = format_ago(data.get("updated_at", ""))
        print(f"⚡ Claude Usage  ·  updated {ago} | {STYLE}")
        print("---")

        # Session
        print(format_tier_line("Session", s))
        print("---")

        # Weekly
        print(format_tier_line("Weekly", w))
        print("---")

        # Extra
        print(format_tier_line("Extra", e))
        print("---")

    # Actions
    ACTION_STYLE = "color=#000000,#ffffff size=13"
    scraper_path = str(SCRIPT_DIR / "scrape-usage-claude.sh")
    print(f"⟳  Refresh Now | {ACTION_STYLE} bash=/bin/bash param1={scraper_path} terminal=false refresh=true")
    print(f"---")
    print(f"📂  Open Config | {ACTION_STYLE} bash=/usr/bin/open param1={str(CONFIG_DIR)} terminal=false")
    print(f"📖  Edit usage.json | {ACTION_STYLE} bash=/usr/bin/open param1={str(USAGE_FILE)} terminal=false")
    history_script = str(SCRIPT_DIR / "build-history.py")
    print(f"📊  View History | {ACTION_STYLE} bash={PYTHON} param1={history_script} param2=--open terminal=false")


if __name__ == "__main__":
    main()
