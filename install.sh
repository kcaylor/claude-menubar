#!/bin/bash
# install.sh — Install Claude Usage Monitor for SwiftBar
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
CONFIG_DIR="$HOME/.config/claude-menubar"

echo "⚡ Installing Claude Usage Monitor..."
echo ""

# ── Check prerequisites ──
if ! command -v claude &>/dev/null; then
    echo "❌ Claude Code CLI not found."
    echo "   Install: https://docs.anthropic.com/en/docs/claude-code"
    echo "   Then run: claude  (and sign in)"
    exit 1
fi

if ! command -v tmux &>/dev/null; then
    echo "❌ tmux not found. Install: brew install tmux"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Install: brew install python3"
    exit 1
fi

# Check for SwiftBar (or xbar) plugin directory
if [[ ! -d "$PLUGIN_DIR" ]]; then
    # Try xbar
    PLUGIN_DIR="$HOME/Library/Application Support/xbar/plugins"
    if [[ ! -d "$PLUGIN_DIR" ]]; then
        echo "❌ SwiftBar/xbar plugin directory not found."
        echo "   Install SwiftBar: brew install swiftbar"
        echo "   Then launch it and set a plugin folder."
        exit 1
    fi
    echo "📦 Detected xbar (using $PLUGIN_DIR)"
else
    echo "📦 Detected SwiftBar"
fi

# ── Create config directory ──
mkdir -p "$CONFIG_DIR"

# ── Make scripts executable ──
chmod +x "$SCRIPT_DIR/claude-usage.10m.py"
chmod +x "$SCRIPT_DIR/scrape-usage-claude.sh"
echo "✅ Scripts marked executable"

# ── Symlink plugin ──
PLUGIN_LINK="$PLUGIN_DIR/claude-usage.10m.py"
if [[ -L "$PLUGIN_LINK" || -f "$PLUGIN_LINK" ]]; then
    rm "$PLUGIN_LINK"
fi
ln -sf "$SCRIPT_DIR/claude-usage.10m.py" "$PLUGIN_LINK"
echo "🔗 Linked plugin → $PLUGIN_DIR"

# ── Run first scrape ──
echo ""
echo "📊 Fetching initial usage data (this takes ~10 seconds)..."
if bash "$SCRIPT_DIR/scrape-usage-claude.sh" 2>/dev/null; then
    echo "✅ Got usage data!"
else
    echo "⚠  Couldn't fetch data on first try."
    echo "   Make sure 'claude' CLI is signed in, then run:"
    echo "   bash $SCRIPT_DIR/scrape-usage-claude.sh"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Installed! Look for the bars in your menu bar."
echo ""
echo "  📊 View dropdown  → Click the bars icon"
echo "  ⟳  Manual refresh → Click 'Refresh Now' in the dropdown"
echo "  📈 History chart  → Click 'View History' in the dropdown"
echo ""
echo "  Data: $CONFIG_DIR/usage.json"
echo "  Logs: $CONFIG_DIR/history.jsonl"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
