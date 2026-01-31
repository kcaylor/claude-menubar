#!/usr/bin/env python3
"""
Build data.json from history.jsonl for the usage history dashboard.
Normalizes all entries to a consistent format and deduplicates.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

CONFIG_DIR = Path.home() / ".config" / "claude-menubar"
HISTORY_FILE = CONFIG_DIR / "history.jsonl"
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "data.json"

def normalize(entry: dict) -> dict | None:
    """Normalize a history entry to consistent format."""
    ts = entry.get("ts") or entry.get("updated_at")
    if not ts:
        return None
    
    # Skip event-only entries (resets, etc.)
    if "event" in entry and "session" not in entry:
        return None
    
    session = entry.get("session", {})
    weekly = entry.get("weekly", {})
    extra = entry.get("extra", {})
    
    # Compute remaining_pct from used if needed
    def get_remaining(tier):
        if "remaining_pct" in tier:
            return tier["remaining_pct"]
        if "used" in tier and "limit" in tier and tier["limit"] > 0:
            return max(0, (1 - tier["used"] / tier["limit"])) * 100
        return None
    
    s_remain = get_remaining(session)
    w_remain = get_remaining(weekly)
    e_remain = get_remaining(extra)
    
    if s_remain is None and w_remain is None:
        return None
    
    result = {
        "ts": ts,
        "session": {
            "remaining_pct": s_remain if s_remain is not None else 100,
            "used": session.get("used", 0),
        },
        "weekly": {
            "remaining_pct": w_remain if w_remain is not None else 100,
            "used": weekly.get("used", 0),
        },
        "extra": {
            "remaining_pct": e_remain if e_remain is not None else 100,
            "spent": extra.get("spent", 0),
            "cap": extra.get("cap", 100),
        },
    }
    # Preserve reset_at timestamps for annotation lines
    if session.get("reset_at"):
        result["session"]["reset_at"] = session["reset_at"]
    if weekly.get("reset_at"):
        result["weekly"]["reset_at"] = weekly["reset_at"]
    if extra.get("reset_at"):
        result["extra"]["reset_at"] = extra["reset_at"]
    return result


def main():
    if not HISTORY_FILE.exists():
        print(f"❌ No history file at {HISTORY_FILE}", file=sys.stderr)
        sys.exit(1)
    
    entries = []
    seen_ts = set()
    
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                norm = normalize(raw)
                if norm and norm["ts"] not in seen_ts:
                    entries.append(norm)
                    seen_ts.add(norm["ts"])
            except json.JSONDecodeError:
                continue
    
    # Sort by timestamp
    entries.sort(key=lambda e: e["ts"])
    
    with open(OUTPUT_FILE, "w") as f:
        json.dump(entries, f)
    
    print(f"✅ {len(entries)} entries → {OUTPUT_FILE}")
    
    # Build the dashboard HTML with inlined data
    html_template = SCRIPT_DIR / "usage-history.html"
    html_out = CONFIG_DIR / "dashboard.html"
    
    with open(html_template) as f:
        html = f.read()
    
    # Inject data as inline JS variable before the loadData() call
    data_js = f"\nvar INLINE_DATA = {json.dumps(entries)};\n"
    html = html.replace("let RAW_DATA = [];", f"let RAW_DATA = [];\n{data_js}")
    
    with open(html_out, "w") as f:
        f.write(html)
    
    print(f"📄 Dashboard → {html_out}")
    
    # Open the dashboard if --open flag
    if "--open" in sys.argv:
        import subprocess
        subprocess.run(["open", str(html_out)])
        print(f"🌐 Opened {html_out}")


if __name__ == "__main__":
    main()
