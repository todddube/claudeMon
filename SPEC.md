# claudeMon: analysis and spec

Source material: the r/ClaudeCode post "Made a Taskmanager for Claude Code" (Himamushi, by
u/FreXxXenstein), its comment thread, and nine screenshots of it (kept locally, not in this repo). This file
breaks down what Himamushi does, what the comments asked for, and how claudeMon builds
each part as a terminal UI.

## 1. What Himamushi is

A local web dashboard (Python stdlib server + plain HTML/CSS/JS) that reads Claude Code's
transcripts and status line and answers three questions:

1. Which agent is running, and how hard?
2. Will I hit my session (5 h) or weekly cap, and when?
3. What model and effort is each running thing using?

The author says it already paid off: some agents were running at `xhigh` effort when
`medium` was intended, and some tasks didn't need Opus.

### Pages, from the screenshots

| Page | What it shows | Notes |
|---|---|---|
| **Token burn** | One area chart per session (tok/min) on a shared scale; state badge (● Working / ▲ Needs you / ○ Idle); context % per tile. A footer with Burn now, Output now and the counts per state, plus the session names grouped by state. | Graph range 1 m / 5 m / 15 m / 1 h; Show Overall / Sessions. |
| **Context** | Fullest and average context fill. | Sidebar only in the screenshots. |
| **Prompt cache** | Hit-ratio chart, cache writes/min chart. Stats: Hit ratio, Warm *n of m*, Reads now, Writes now, Misses (5 min). A table per session: Warm/Cold, *Expires in* countdown, time-left bar, Hit %, Misses, **Re-cache if cold** (tokens you'd pay to rebuild). | The re-cache column is the clever part: it prices letting a session go idle past the TTL. |
| **Traffic** | Tokens out vs in. | Sidebar only. |
| **Models** | One chart per model with its share of output. Under each: the effort split ("medium 11% · xhigh 89%") and *Used by* (sessions/subagents with %). Thinking share of output. | Show Model / Model·effort toggle. |
| **Session limit** | 5 h window chart of observed %. A dashed projection with an uncertainty fan to "full ≈ 15:40", and the time between projected-full and reset hatched. Now: Used, Hourly rate, Session rate (%/5 h). Forecast: Projected / Worst / Best. | Data scope This session / Today / Last 7 days / This week; method Min/max. A Day view shows several 5 h windows side by side. |
| **Weekly limit** | Same layout over the 7-day window; rate in %/day. | Week / Zoom / 7 / 8 days. |
| **Projects** | Weekly limit used, total tokens. Ranked bars of each project's share of the weekly limit (≈ %), sub-rows per folder, and day-of-week mini bars. Composition, over-the-week and pie views. | |
| **Settings** | 10 themes (Modern, Pinstripe/Aqua, Bevel/Win95, Breadbin/C64, Glass…). | |

Shared chrome: a left sidebar where each page has a live mini-graph and two stat lines, an update
selector (1/2/5/10 s), and the build and version in the footer.

### Stated limits

- One machine only: it sees only that machine's sessions. Usage from the phone, the web or another PC shows
  up only as jumps in the account %.
- Limit views need Pro/Max/Team/Ultra, because the status line carries no `rate_limits` otherwise.
- Claude Desktop and Cowork are not seen directly. Their usage appears only through the account %.

## 2. What the comment thread asked for

| Ask (who) | Why it matters | claudeMon |
|---|---|---|
| **Re-read loop detector**: "group reads by file path within a session and flag anything read 3+ times with no edit in between … a red badge on the session row" | The biggest silent limit-burner is an agent re-reading the same files while you're not looking. | `⟲n` badge on burn tiles, a Loops counter, a **Loop watch** panel in Inspect, and `claudemon loops` as a standalone report. Counters reset on compaction, where re-reads are expected. |
| **Unattributed usage**: show "last observed", separate account usage from local sessions, label jumps as *unattributed*, say "insufficient data" instead of a precise-looking countdown | A fresh local session must not inherit a burn rate from phone usage. | A gap over 15 min with a rise is a **blind spot**: drawn as ░, left out of every rate, listed with the local tokens spent in it. Each forecast shows *observed Xm ago* and flags *stale* or *insufficient recent data*. |
| Rolling window or whole-session trend? | | **Projected** = rolling window (1 h for 5 h, 24 h for weekly). **Best** = period average. **Worst** = busiest slice (15 min / 6 h). All three use attributed intervals only. |
| Per-session burn vs one rate | | Burn is per session. Limits are account-wide, because that's all Claude Code reports. |
| **"Which one needs you"**: found a session stuck on a permission prompt 10 min late | | ▲ Needs you, sorted to the top and bold in the header. It comes from the tap's Notification hook (`permission_prompt`) or, without the hook, from a quick tool waiting over 45 s. |
| Drill down into a session (OP: "you can't click on the sessions") | | **Inspect** page (⏎ from any list): model/effort/mode, context gauge, cost, subagents with their own model/effort/tok-min, top tools, loop watch. |
| Mac support, dark mode | | macOS-first; all themes are dark by default; `--window` opens a dedicated Terminal/iTerm/Ghostty window. |
| How much does the monitor itself use? | | Zero tokens. It reads local files only. |
| Cross-machine | | Out of scope. Blind-spot jumps make other machines' usage visible without any networking. |

## 3. Data sources (verified on this machine, Claude Code 2.1.311)

| File | Fields used |
|---|---|
| `~/.claude/sessions/<pid>.json` | `pid`, `sessionId`, `cwd`, `name`, `status` (busy/idle), `kind`. Liveness = `kill(pid, 0)`. |
| `~/.claude/projects/<proj>/<sid>.jsonl` | `assistant` → `message.id`, `model`, `usage{input, output, cache_read, cache_creation{ephemeral_1h,5m}, output_tokens_details.thinking_tokens}`, `tool_use{name, id, input.file_path}`; `user` → `tool_result.tool_use_id`; `api-request` → `params.model`, `output_config.effort`; `permission-mode`; `ai-title`; `last-prompt`; `system/compact_boundary`. |
| `…/<sid>/subagents/agent-*.jsonl` + `.meta.json` | The same transcript format, plus `agentType`, `description`, `finished`. |
| Status-line stdin (via tap) | `rate_limits.five_hour/seven_day.{used_percentage, resets_at}`, `context_window.context_window_size`, `cost.total_cost_usd`, `effort.level`. |
| Notification hook stdin (via tap) | `notification_type` (`permission_prompt`, `idle_prompt`, …), `message`. |

Parsing gotchas the code handles:

- **Streaming duplicates.** One API message is written several times with the same `message.id` and growing usage. Usage is keyed by id and the last copy wins, and tool_use ids are de-duplicated.
- **Huge lines.** `api-request-blob` and `api-request-shape` records hold whole prompts. They're skipped by peeking at the first 80 bytes, before JSON parsing.
- **Incremental tailing** by byte offset, holding back a partial last line. A file that shrinks is re-read from the start.
- **Cache TTL** comes from the last cache *write* (1 h vs 5 m). A pure cache-read call doesn't tell you the TTL.
- **Context size** = `input + cache_read + cache_write` of the latest call. The window size comes from the tap, falling back to the model family (Opus 5 / Fable → 1M).

Indexing a week of history (≈50 MB, 24 files here) takes about 0.4 s at startup, in a background thread.

## 4. claudeMon design

A terminal UI in the style of btop, syswatch and netwatch: Python stdlib only (`curses`), no install step.

```
╭ header: ◆ claudeMon │ n live ● working ▲ needs you ○ idle            ● ⟳ 2s theme hh:mm:ss
│ sidebar (26 cols)         │ page
│ 1 Token burn              │ ╭─┤panel title├───────────────┤right info├╮
│   ▂▃▅▇ 2 sessions         │ │ gradient block / braille charts          │
│        1.04M tok/min      │ ╰──────────────────────────────────────────╯
│ … one entry per page, each with a live sparkline and two stat lines
╰ footer: key hints                                          flash / version
```

- **Graphs.** Solid `▁▂▃▄▅▆▇█` blocks by default. `b` switches to braille (2×4 dots per cell), which is used for limit projections in either mode.
- **Colour.** 256-colour themes. Graphs and gauges are coloured by height through a 5-step gradient, and states use ok/warn/crit.
- **Themes (10):** claude, btop, dracula, nord, gruvbox, matrix, amber, c64, synthwave, mono. `t` cycles through them, and Settings shows live swatches.
- **Pages:** 1 Token burn · 2 Tasks · 3 Context · 4 Prompt cache · 5 Traffic · 6 Models · 7 Session limit · 8 Weekly limit · 9 Projects · 0 Inspect · s Settings.
- **Tasks** is a live tree of everything running: sessions, tool calls in flight, subagents, background shells, spawned processes, MCP servers, queued prompts, Claude Desktop, daemon jobs and scheduled tasks, with a detail pane (including a live tail of a background task's output).
- **Manual** (`m`) is built in: one chapter per page, plus the tap, the Claude Code tools and the data sources. It opens on the page you are viewing.
- **The tap is highlighted everywhere it matters:** a yellow `⚡ tap off: press I` chip in the header and footer, `⚡ install tap` in the sidebar, a full callout on the limit pages, and a one-time prompt on first launch (install now, or later).
- **Keys:** `1-0` page, `←→`/Tab page, `↑↓`/jk select, `⏎` inspect, `g` range (5m/15m/1h/6h/24h), `o` overall, `e` model·effort, `a` include finished sessions, `t` theme, `b` graph style, `u` update interval, `r` refresh, `m` manual, `?` help, `q` quit; `I I` installs the tap from any page, `U U` removes it on Settings (both ask for a second press).
- **State** is kept in `~/.claude/claudemon/` (config, limits log, status snapshots, settings backups). claudeMon never writes inside Claude Code's own files.

### Module map

| Module | Role |
|---|---|
| `transcript.py` | Incremental JSONL parser: calls, tools, pending tools, loop counters, cache TTL |
| `store.py` | Session discovery, live registry, subagents, state machine, time-bucketed series |
| `limits.py` | Limit log reader, blind-spot detection, projected/worst/best forecast |
| `tap.py` | Standalone status-line passthrough and hook recorder (no package imports, fails silent) |
| `install.py` | Reversible settings.json edits, with a timestamped backup before every write |
| `draw.py` / `themes.py` | Colour pairs, rounded panels, gradient gauges, block and braille charts |
| `tui.py` | App loop, the eleven pages, the manual viewer and the first-run prompt |
| `tasks.py` | Builds the Tasks tree from sessions, subagents, background tasks, processes, jobs |
| `procs.py` | One `ps` snapshot: claude CLIs, their children (MCP servers, shells), Claude Desktop |
| `manual.py` | The built-in manual's text |
| `claudemon.py` | Entry point and command line |
| `launch.py` | `--window`: opens Terminal / iTerm / Ghostty (or a Linux terminal) titled claudeMon |
| `tools/make_demo.py` | Generates a synthetic `~/.claude` tree (sessions, subagents, limits with a blind spot) |
| `tools/grid.py`, `tools/shots.py` | Headless screen capture and the README screenshot renderer |

### Approximations

- **Projects share** weights tokens by rough relative cost: output ×5, cache write ×1.25, input ×1, cache read ×0.1. Anthropic doesn't publish how usage limits weight tokens, so "≈ % of weekly" is the project's weighted share × the weekly %. Treat it as indicative.
- **Needs you** without the hook is a heuristic: a non-long-running tool (not Bash, Agent or a web call) pending over 45 s with no transcript writes.

## 5. Next steps

- A Day view for the session limit, showing several 5 h windows side by side like Himamushi's "Session limits today".
- An effort-mismatch alert, for example `xhigh` on a subagent whose parent runs `medium`. This is the insight that saved Himamushi's author a week.
- Cache-cold warnings: "session X goes cold in 2 min; re-cache costs 680k".
- Mouse support (click a sidebar entry or a tile).
- Kill or interrupt controls on the Tasks page (read-only today, on purpose).
- An optional SQLite cache, if indexing more than a week becomes slow.
