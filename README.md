# ⚡ Claude Usage Monitor for SwiftBar

A macOS menu bar widget that shows your [Claude](https://claude.ai) usage limits at a glance — session, weekly, and extra spend — with colored pacing indicators and an interactive history dashboard.

<img src="screenshots/menubar.png" width="340" alt="Menu bar dropdown">
<img src="screenshots/dashboard.png" width="700" alt="History dashboard">

## Features

- **Menu bar icon** — three tiny colored bars (green/yellow/red) showing session, weekly, and extra usage pacing
- **Dropdown details** — remaining %, reset countdown, and pace warnings for each tier
- **Auto-refresh** — updates every 10 minutes via [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- **History dashboard** — interactive stock-chart style visualization with time range filters
- **Zero browser automation** — no Cloudflare issues, no CDP, no cookies to manage

## How It Works

The plugin calls Claude Code's built-in `/usage` command to fetch your current plan limits. No API keys, no browser scraping, no session cookies needed — just a locally installed Claude Code CLI that's signed in to your account.

```
scrape-usage-claude.sh  →  launches claude CLI  →  /usage  →  parses output  →  usage.json
claude-usage.10m.py     →  reads usage.json    →  renders menu bar icon + dropdown
build-history.py        →  reads history.jsonl  →  builds interactive HTML dashboard
```

## Requirements

- **macOS** with [SwiftBar](https://github.com/swiftbar/SwiftBar) (or [xbar](https://xbarapp.com/))
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** (`claude`) — installed and signed in
- **Python 3.10+** (ships with macOS or via Homebrew)
- **tmux** (ships with macOS or `brew install tmux`)

## Installation

### Quick Install

```bash
git clone https://github.com/kellycaylor/claude-menubar.git
cd claude-menubar
./install.sh
```

### Manual Install

1. **Clone the repo** somewhere on your Mac:
   ```bash
   git clone https://github.com/kellycaylor/claude-menubar.git ~/dev/claude-menubar
   ```

2. **Symlink the plugin** into your SwiftBar plugins folder:
   ```bash
   ln -sf ~/dev/claude-menubar/claude-usage.10m.py \
     "$HOME/Library/Application Support/SwiftBar/Plugins/claude-usage.10m.py"
   ```

3. **Make scripts executable:**
   ```bash
   chmod +x ~/dev/claude-menubar/claude-usage.10m.py
   chmod +x ~/dev/claude-menubar/scrape-usage-claude.sh
   ```

4. **Verify Claude Code is signed in:**
   ```bash
   claude --version
   ```

5. **Run the first scrape** to populate data immediately:
   ```bash
   ~/dev/claude-menubar/scrape-usage-claude.sh
   ```

SwiftBar will pick up the plugin within a few seconds.

## Usage

### Menu Bar

The menu bar shows three colored vertical bars representing your usage pacing:

| Color | Meaning |
|-------|---------|
| 🟢 Green | Comfortable — well ahead of pace |
| 🟡 Yellow | Watch it — burning a bit fast |
| 🟠 Orange | Slow down — approaching limit |
| 🔴 Red | Near limit — conserve usage |

Click the icon to see the dropdown with exact numbers and reset countdowns.

### Refreshing

- **Automatic**: SwiftBar refreshes the display every 10 minutes and triggers a background data fetch
- **Manual**: Click **⟳ Refresh Now** in the dropdown

### History Dashboard

Click **📊 View History** in the dropdown to open an interactive HTML dashboard showing:

- **Session Usage** — current session with reset countdown annotation
- **Weekly Usage** — all-models usage for the current week  
- **Monthly Extra Spend** — cumulative spend vs. monthly cap

Time range filters: *This Session · Today · 24 Hours · This Week · Last Week · All Data*

## Files

| File | Purpose |
|------|---------|
| `claude-usage.10m.py` | SwiftBar plugin — renders menu bar icon and dropdown |
| `scrape-usage-claude.sh` | Data fetcher — launches Claude Code, runs `/usage`, writes `usage.json` |
| `build-history.py` | Builds the interactive HTML dashboard from `history.jsonl` |
| `usage-history.html` | Dashboard template (Chart.js) |
| `install.sh` | One-line installer |

### Data Files (in `~/.config/claude-menubar/`)

| File | Purpose |
|------|---------|
| `usage.json` | Current usage snapshot (read by the SwiftBar plugin) |
| `history.jsonl` | Append-only log of all usage snapshots |
| `dashboard.html` | Built dashboard with inlined data |

## Configuration

### Refresh Interval

The filename `claude-usage.10m.py` controls the refresh interval. Rename to change:
- `claude-usage.5m.py` — every 5 minutes
- `claude-usage.30m.py` — every 30 minutes

Remember to update the symlink after renaming.

### Color Tuning

Edit the `pace_score()` and `score_to_rgb()` functions in `claude-usage.10m.py` to adjust the color thresholds and gradient.

### Bar Geometry

The `ICON_H`, `BAR_W`, `BAR_H`, `GAP`, and `CORNER_R` constants at the top of the plugin control the menu bar icon dimensions.

## Troubleshooting

**"No usage data yet"**  
Run the scraper manually: `bash scrape-usage-claude.sh --debug`

**Scraper fails or times out**  
Make sure `claude` CLI is installed and signed in:
```bash
which claude
claude --version
```

**SwiftBar doesn't show the plugin**  
Check the symlink: `ls -la "$HOME/Library/Application Support/SwiftBar/Plugins/"`.
Make sure the file is executable: `chmod +x claude-usage.10m.py`

**Dashboard shows "No data"**  
Run `python3 build-history.py --open` to rebuild. The dashboard needs `history.jsonl` to have data points.

## How the Pacing Algorithm Works

The color isn't just based on remaining % — it factors in **time until reset**:

- If you have 50% remaining and 50% of the time window left → **green** (on pace)
- If you have 50% remaining but only 10% of time left → **green** (you'll easily make it)
- If you have 20% remaining and 80% of time left → **red** (burning too fast)

This means the bars get more "forgiving" as you approach the reset time.

## Credits

Built with [SwiftBar](https://github.com/swiftbar/SwiftBar) and [Chart.js](https://www.chartjs.org/). Data sourced from [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI.

## License

MIT — see [LICENSE](LICENSE).
