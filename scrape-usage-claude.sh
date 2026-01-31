#!/bin/bash
# scrape-usage-claude.sh — Get Claude usage via `claude` CLI /usage command
#
# Launches Claude Code in a tmux session, runs /usage, parses output,
# writes ~/.config/claude-menubar/usage.json
#
# Usage:
#   ./scrape-usage-claude.sh           # Scrape and write usage.json
#   ./scrape-usage-claude.sh --debug   # Show raw output

set -euo pipefail

CONFIG_DIR="$HOME/.config/claude-menubar"
USAGE_FILE="$CONFIG_DIR/usage.json"
HISTORY_FILE="$CONFIG_DIR/history.jsonl"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_NAME="claude-usage-scrape"

mkdir -p "$CONFIG_DIR"

log() { echo "$(date '+%H:%M:%S') $*" >&2; }

cleanup() {
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
}
trap cleanup EXIT

# ── Launch Claude Code and capture /usage ──
scrape() {
    # Kill any leftover session
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

    # Start Claude Code in a tmux session
    tmux new-session -d -s "$SESSION_NAME" -x 120 -y 50 \
        "claude --dangerously-skip-permissions"

    # Wait for Claude to be ready (prompt appears)
    local ready=false
    for i in $(seq 1 15); do
        local screen
        screen=$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null || echo "")
        if echo "$screen" | grep -q "❯"; then
            ready=true
            break
        fi
        sleep 1
    done

    if [ "$ready" != "true" ]; then
        log "❌ Claude Code didn't start in time"
        return 1
    fi

    # Type /usage and press Enter
    tmux send-keys -t "$SESSION_NAME" '/usage' Enter

    # Wait for autocomplete menu to appear, then confirm with Enter
    sleep 2
    local screen
    screen=$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null || echo "")
    if echo "$screen" | grep -q "Show plan usage"; then
        # Autocomplete is showing — press Enter to confirm
        tmux send-keys -t "$SESSION_NAME" Enter
    fi

    # Wait for the usage data to appear
    local got_data=false
    for i in $(seq 1 15); do
        sleep 1
        local screen
        screen=$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null || echo "")
        if echo "$screen" | grep -q "% used"; then
            got_data=true
            # Give it a moment to finish rendering
            sleep 2
            break
        fi
    done

    if [ "$got_data" != "true" ]; then
        log "❌ /usage didn't return data"
        tmux capture-pane -t "$SESSION_NAME" -p >&2
        return 1
    fi

    # Capture the full pane
    tmux capture-pane -t "$SESSION_NAME" -p
}

# ── Parse the captured output ──
parse_usage() {
    local raw="$1"

    python3 - "$raw" <<'PYTHON'
import sys, json, re
from datetime import datetime, timezone, timedelta

raw = sys.argv[1]
now = datetime.now(timezone.utc)
pst = timezone(timedelta(hours=-8))
today = now.astimezone(pst)

def parse_time_reset(text):
    """Parse 'Resets Xpm' or 'Resets Feb 6 at 8am' into ISO datetime."""
    # "Resets 4pm" — same day reset
    m = re.search(r'Resets\s+(\d{1,2})(am|pm)', text, re.I)
    if m:
        h = int(m.group(1))
        if m.group(2).lower() == 'pm' and h != 12:
            h += 12
        if m.group(2).lower() == 'am' and h == 12:
            h = 0
        dt = today.replace(hour=h, minute=0, second=0, microsecond=0)
        if dt <= now.astimezone(pst):
            dt += timedelta(days=1)
        return dt.isoformat()

    # "Resets Feb 6 at 8am" — specific date
    m = re.search(r'Resets\s+([A-Z][a-z]+)\s+(\d{1,2})\s+at\s+(\d{1,2})(am|pm)', text, re.I)
    if m:
        month_name, day, h, ampm = m.groups()
        h = int(h)
        day = int(day)
        if ampm.lower() == 'pm' and h != 12:
            h += 12
        if ampm.lower() == 'am' and h == 12:
            h = 0
        month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                     'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        mo = month_map.get(month_name.lower()[:3], 1)
        year = today.year
        dt = datetime(year, mo, day, h, 0, tzinfo=pst)
        if dt <= now.astimezone(pst):
            dt = datetime(year + 1, mo, day, h, 0, tzinfo=pst)
        return dt.isoformat()

    # "Resets 12am" — midnight
    m = re.search(r'Resets\s+12am', text, re.I)
    if m:
        dt = (today + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return dt.isoformat()

    return ""

# Parse session
session = {"remaining_pct": 100, "used": 0, "limit": 100, "window_hours": 5}
m = re.search(r'Current session.*?(\d+)%\s*used.*?Resets\s+(.+?)(?:\n|$)', raw, re.S)
if m:
    session["used"] = int(m.group(1))
    session["remaining_pct"] = 100 - session["used"]
    session["reset_at"] = parse_time_reset("Resets " + m.group(2).strip())
else:
    session["reset_at"] = (now + timedelta(hours=5)).isoformat()

# Parse weekly all models
weekly = {"remaining_pct": 100, "used": 0, "limit": 100, "window_hours": 168}
m = re.search(r'all models\).*?(\d+)%\s*used.*?Resets\s+(.+?)(?:\n|$)', raw, re.S | re.I)
if m:
    weekly["used"] = int(m.group(1))
    weekly["remaining_pct"] = 100 - weekly["used"]
    weekly["reset_at"] = parse_time_reset("Resets " + m.group(2).strip())

# Parse weekly sonnet
detail = "All models"
m_sonnet = re.search(r'Sonnet only\).*?(\d+)%\s*used', raw, re.S | re.I)
if m_sonnet:
    sonnet_remaining = 100 - int(m_sonnet.group(1))
    detail += f" · Sonnet {sonnet_remaining}% remaining"
weekly["detail"] = detail

# Parse extra usage
extra = {"remaining_pct": 100, "spent": 0, "cap": 100.0, "window_hours": 720}
m = re.search(r'Extra usage.*?(\d+)%\s*used.*?\$(\d+\.?\d*)\s*/\s*\$(\d+\.?\d*).*?Resets\s+(.+?)(?:\n|$)', raw, re.S | re.I)
if m:
    extra["remaining_pct"] = 100 - int(m.group(1))
    extra["spent"] = float(m.group(2))
    extra["cap"] = float(m.group(3))
    extra["reset_at"] = parse_time_reset("Resets " + m.group(4).strip())

usage = {
    "session": session,
    "weekly": weekly,
    "extra": extra,
    "updated_at": now.isoformat()
}
print(json.dumps(usage))
PYTHON
}

# ── Main ──
log "🚀 Starting Claude Code for /usage..."
raw=$(scrape)

if [ -z "$raw" ]; then
    log "❌ No output captured"
    exit 1
fi

if [ "${1:-}" = "--debug" ]; then
    echo "=== RAW ==="
    echo "$raw"
    echo "=== END ==="
fi

usage=$(parse_usage "$raw")

if [ -z "$usage" ] || [ "$usage" = "null" ]; then
    log "❌ Failed to parse usage data"
    exit 1
fi

# Write usage.json
echo "$usage" | python3 -m json.tool > "$USAGE_FILE"
log "✅ Written to $USAGE_FILE"

# Append to history
echo "$usage" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['source'] = 'claude-cli'
print(json.dumps(d))
" >> "$HISTORY_FILE" 2>/dev/null || true

# Summary
echo "$usage" | python3 -c "
import sys, json
d = json.load(sys.stdin)
s, w, e = d['session'], d['weekly'], d['extra']
print(f'📊 Session: {s[\"remaining_pct\"]}% | Weekly: {w[\"remaining_pct\"]}% | Extra: \${e.get(\"spent\",0):.2f}/\${e.get(\"cap\",100):.2f}')
" >&2
