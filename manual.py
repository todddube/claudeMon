"""The built-in manual (press m). One topic per page plus reference chapters.

Body markup, one entry per paragraph:
  "# text"   heading            "- text"   bullet
  "! text"   highlighted callout (used for the tap)
  "> k | t"  key line: key k, description t
  ""         blank line         anything else: a wrapped paragraph
"""

TAP_CALLOUT = [
    "! ⚡ Needs the claudeMon tap. Press I (twice to confirm) on any page, or run `claudemon install`. "
    "Your status line keeps working; `claudemon uninstall` restores settings.json exactly.",
]

TOPICS = [
    dict(id="welcome", title="Welcome", body=[
        "# claudeMon: a task manager for Claude Code",
        "claudeMon watches every Claude Code session on this computer: how fast each one burns tokens, "
        "how full its context is, whether its prompt cache is warm, which model and effort it runs, "
        "what its subagents and background tasks are doing, and when you will hit your session or "
        "weekly limit.",
        "It only reads files Claude Code already writes under ~/.claude, plus a process list. It "
        "sends nothing anywhere and uses no tokens.",
        "# Getting around",
        "> 1-9 0 s | jump to a page (s = Settings)",
        "> ← → Tab | previous / next page",
        "> ↑ ↓ j k | select a session or row",
        "> ⏎ | open the selected session in Inspect",
        "> m | this manual (opens on the page you are viewing)",
        "> ? | quick key reference",
        "> z | mini view (see below)",
        "> q Esc | quit",
        "# Mini view",
        "Press z for a small window that keeps the essentials in sight: both limits with their "
        "forecast, the overall burn, prompt cache warmth, and one line per live session with its "
        "state, model and effort, context, tokens per minute and the tool it is running (◇ subagents, "
        "⟲ re-read loops). Sessions that need you sort to the top.",
        "claudeMon resizes the window to fit the session list, and puts the old size back when you "
        "press z again or quit. Terminal and iTerm honour this; in other terminals, tmux or a "
        "full-screen window the size stays as it is. In mini, ⏎ opens Inspect and a page key opens "
        "that page, both in the full view. `claudemon --mini` starts in it, and it is remembered.",
        "# Two things that need the tap",
        "Most pages work out of the box. The Session limit and Weekly limit pages, the per-session "
        "cost, the exact context window size and reliable ‘Needs you’ alerts all come from the tap. "
        "See the ‘The tap’ chapter.",
        *TAP_CALLOUT,
    ]),
    dict(id="tap", title="⚡ The tap", body=[
        "# Why a tap is needed",
        "Claude Code tells nobody your account limits except its own status line. Each time the status "
        "line refreshes, Claude Code pipes a JSON document into your status-line command. It includes "
        "rate_limits (5-hour and 7-day used % and reset time), the context window size, the session "
        "cost and the effort level.",
        "The tap is a small script (tap.py) that sits in front of your status-line command. "
        "It saves a copy of that JSON for claudeMon, then runs your original command on the same input, "
        "so your status line looks exactly the same.",
        "# What installing changes",
        "- statusLine.command becomes: python3 …/tap.py statusline -- '<your original command>'",
        "- A Notification hook is added: python3 …/tap.py hook Notification  # claudemon",
        "- settings.json is backed up to ~/.claude/claudemon/settings.<time>.bak.json before every change",
        "- Your original status line is also saved to ~/.claude/claudemon/statusline.backup.json",
        "# What it records",
        "- ~/.claude/claudemon/status/<session>.json: the latest status-line input per session",
        "- ~/.claude/claudemon/limits.jsonl: one line per limit change, or one per minute when unchanged",
        "- ~/.claude/claudemon/status/<session>.hook.json: the last notification, e.g. permission_prompt",
        "# Install / remove",
        "> I I | install from any page (press twice to confirm)",
        "> U U | uninstall from the Settings page (press twice to confirm)",
        "> claudemon install | the same from a shell",
        "> claudemon uninstall | restore your original status line and remove the hook",
        "The tap never blocks: if anything fails it stays silent and your status line still prints. "
        "Limits need a Pro, Max, Team or Enterprise login. Other logins send no rate_limits.",
        *TAP_CALLOUT,
    ]),
    dict(id="Token burn", title="1 Token burn", page="Token burn", body=[
        "# What it shows",
        "One panel per live session with a chart of tokens per minute (input + cache + output), all on "
        "one shared scale so a busy session stands out. The badge says what the session is doing:",
        "- ● Working: Claude is generating or running tools",
        "- ▲ Needs you: waiting on a permission prompt or a question (sorted first, bold in the header)",
        "- ○ Idle: finished its turn, waiting for your next prompt",
        "The panel footer shows model · effort, context fill and the tokens of the last minute. A red "
        "⟲n tag means n files are being re-read in a loop (see Inspect → Loop watch).",
        "The Now strip totals the last 60 seconds across all sessions and lists sessions by state.",
        "# How to read it",
        "A tall, steady wall is usually cache reads on a big context, cheap but a sign context is large. "
        "Spikes of output are real work. A session at a constant high burn with no visible progress is "
        "worth inspecting.",
        "# Keys",
        "> g / G | graph range 5m · 15m · 1h · 6h · 24h",
        "> o | one overall chart with an output overlay line",
        "> a | include sessions that ended during the range",
        "> b | cycle the graph style: blocks, braille, dots, line, ascii (previews on Settings)",
        "‘Needs you’ is exact with the tap’s Notification hook. Without it claudeMon guesses: a quick "
        "tool (not Bash, Agent, web or Monitor) pending over 45 s with no transcript writes.",
    ]),
    dict(id="Tasks", title="2 Tasks", page="Tasks", body=[
        "# What it shows",
        "A live tree of everything Claude is doing on this machine, refreshed every tick:",
        "- ◆ each live Claude Code session: model · effort, memory, CPU and state",
        "- ⚙ tool calls in flight: the tool and what it is doing (the command, file or pattern) with "
        "its running time. Yellow = a quick tool waiting suspiciously long, usually a prompt for you",
        "- ◇ subagents still running: description, type, model · effort, tokens/min and age, with "
        "their own in-flight tools nested under them",
        "- ⧗ background shells (run_in_background) still running; ✓ / ✗ ones that finished in the "
        "last 10 minutes with their result",
        "- ▸ processes the CLI has spawned right now (shell commands, dev servers, builds)",
        "- ⌁ MCP servers the session runs, grouped",
        "- ✉ prompts you queued while Claude was busy",
        "- other claude processes without a session file (claude -p, SDK runs) and Claude Desktop",
        "- background jobs from the Claude daemon and your scheduled tasks",
        "# Detail pane",
        "Select any row with ↑ ↓ and the right-hand pane shows everything about it: the full command, "
        "process arguments, timing, the subagent’s transcript, a job’s ‘needs’ question. For a "
        "background shell it shows a live tail of its output file.",
        "> ↑ ↓ | move through the tree",
        "> ⏎ | on a session or subagent: open the session in Inspect",
    ]),
    dict(id="Context", title="3 Context", page="Context", body=[
        "# What it shows",
        "How full each session’s context window is: tokens the model saw on its latest call (fresh "
        "input + cache reads + cache writes) against the window size, with a gauge, the number of "
        "compactions, and a sparkline of context size over the graph range.",
        "Below the table, a chart of context size per call for the selected session shows growth "
        "and the drop after each compaction.",
        "# Why it matters",
        "Every call re-sends the whole context. A session at 80% of a 1M window sends ~800k tokens per "
        "call (cheap if cached, expensive if not) and is close to auto-compaction, which loses detail.",
        "The window size comes from the tap. Without it, claudeMon assumes 1M for Opus 5 and Fable and "
        "200k for others.",
    ]),
    dict(id="Prompt cache", title="4 Prompt cache", page="Prompt cache", body=[
        "# What it shows",
        "- Hit ratio: share of prompt tokens served from cache over time (high is good)",
        "- Cache writes per minute: tokens newly written to the cache (writes cost more than input)",
        "- Warm: sessions whose cache has not expired. The TTL is 1 hour or 5 minutes, taken from the "
        "session’s last cache write",
        "- Misses, 5 min: calls over 2k tokens that read under 10% from cache",
        "# The sessions table",
        "- Expires / Time left: when the session’s cache goes cold if you don’t send anything",
        "- Re-cache if cold: the context size you will pay to rewrite into the cache on your next "
        "message after it expires. Large numbers mean ‘reply before the timer runs out’",
    ]),
    dict(id="Traffic", title="5 Traffic", page="Traffic", body=[
        "# What it shows",
        "Three charts per minute: tokens out (generated, including thinking), fresh input (uncached "
        "input + cache writes) and cache reads, plus totals for the range and the thinking share of "
        "output.",
        "Output and fresh input are what drive cost and limits most. Cache reads are numerous but cheap.",
    ]),
    dict(id="Models", title="6 Models", page="Models", body=[
        "# What it shows",
        "One chart per model with its share of output tokens. Under each: the effort split (low · "
        "medium · high · xhigh) and which sessions and subagents use it.",
        "> e | split by model · effort instead of model",
        "# What to look for",
        "Subagents on a bigger model or a higher effort than the job needs. The Himamushi author found "
        "agents on xhigh instead of medium, and simple tasks on Opus. Fixing those stretched a week’s "
        "limit.",
    ]),
    dict(id="Session limit", title="7 Session limit", page="Session limit", body=[
        "# What it shows",
        "Your 5-hour usage window: observed used % over time (filled), the current-rate projection "
        "(dashed, red), plus best and worst projections (dotted). It also shows ‘full ≈ hh:mm’ and a "
        "hatched zone between projected-full and the reset, the time you would be locked out.",
        "# The forecast",
        "- Projected: the rate over the last hour",
        "- Worst: the busiest 15-minute slice this window",
        "- Best: the average since the window started",
        "- ‘after reset’ means you will not hit the cap before it resets",
        "# Blind spots",
        "If usage rises while this machine recorded nothing for 15+ minutes (phone, web, another "
        "computer), that jump is shaded ░, listed as ‘unattributed’ with the local tokens spent "
        "meanwhile, and left out of every rate. A fresh local session never inherits someone else’s "
        "burst. ‘observed Xm ago’ and ‘stale’ / ‘insufficient data’ tell you how much to trust it.",
        *TAP_CALLOUT,
    ]),
    dict(id="Weekly limit", title="8 Weekly limit", page="Weekly limit", body=[
        "# What it shows",
        "The same as Session limit over the 7-day window. Rates are %/day: Projected uses the last "
        "24 hours, Worst the busiest 6-hour slice, Best the week-to-date average.",
        *TAP_CALLOUT,
    ]),
    dict(id="Projects", title="9 Projects", page="Projects", body=[
        "# What it shows",
        "Each project’s (working folder’s) share of usage since the weekly limit last reset (or the last "
        "7 days), with the top models inside it and a bar per day of the week. With the tap, ‘of wk’ "
        "estimates how many points of your weekly limit each project used.",
        "# How shares are weighted",
        "Anthropic does not publish how limits weigh token types, so shares use rough relative cost: "
        "output ×5, cache writes ×1.25, input ×1, cache reads ×0.1. Treat them as indicative.",
    ]),
    dict(id="Inspect", title="0 Inspect", page="Inspect", body=[
        "# What it shows",
        "Everything about one session: state and the tool it is waiting on, title, project, branch, "
        "model and effort, permission mode, PID, running time, tokens, cost (tap), compactions, API "
        "errors, context gauge and your last prompt.",
        "- Tokens / min: the session including its subagents",
        "- Top tools: which Claude Code tools it uses most",
        "- Subagents: every subagent with type, model, effort, output, current rate and status",
        "- Loop watch: files read 3+ times with no edit in between, the signature of an agent going in "
        "circles. Counters reset at each compaction because re-reading after one is normal",
        "> ↑ ↓ | switch session",
        "`claudemon loops` prints the same loop report in a shell.",
    ]),
    dict(id="Settings", title="s Settings", page="Settings", body=[
        "# What it shows",
        "The theme picker with colour swatches, where each source of data comes from and whether the "
        "tap and hook are installed, plus how many limit samples have been recorded.",
        "> ↑ ↓ ⏎ | choose a theme (or press t anywhere to cycle)",
        "> I I | install the tap",
        "> U U | uninstall the tap",
        "> u | update interval 1 · 2 · 5 · 10 s",
        "Preferences are saved to ~/.claude/claudemon/config.json.",
    ]),
    dict(id="tools", title="Claude Code tools", body=[
        "# The tools you will see in Tasks and Inspect",
        "- Read: reads a file. Repeated reads of one file with no edit trigger Loop watch",
        "- Edit / Write / MultiEdit / NotebookEdit: change files, which resets that file’s loop counter",
        "- Bash: runs a shell command. Long ones may run in the background (⧗) with an output file",
        "- Grep / Glob: search file contents / names",
        "- Agent (Task): starts a subagent with its own context, model and effort, shown as ◇",
        "- WebFetch / WebSearch: fetch a page / search the web",
        "- Skill: loads a packaged instruction set",
        "- Monitor: waits on a background condition",
        "- mcp__…: tools from an MCP server (the ⌁ processes)",
        "# Why some tools are ‘long’",
        "Bash, Agent, WebFetch, WebSearch and Monitor can legitimately run for minutes, so they never "
        "trigger the ‘Needs you’ guess. A Read or Edit pending for 45 s almost always means a "
        "permission prompt is waiting.",
    ]),
    dict(id="sources", title="Data sources", body=[
        "# Read-only sources",
        "- ~/.claude/sessions/<pid>.json: live sessions: pid, name, busy / idle",
        "- ~/.claude/projects/<project>/<session>.jsonl: transcripts with every API call’s usage, "
        "model, effort, tool calls, background tasks and queued prompts",
        "- …/<session>/subagents/agent-*.jsonl + .meta.json: subagent transcripts",
        "- ~/.claude/jobs/*/state.json: background jobs run by the Claude daemon",
        "- ~/.claude/scheduled-tasks/*/SKILL.md: scheduled tasks",
        "- ps: the process tree of every claude CLI and Claude Desktop",
        "# Written by claudeMon",
        "Only ~/.claude/claudemon/: config, tap snapshots, the limits log and settings backups. The "
        "only change to Claude Code’s own files is the tap install, and only when you ask for it.",
        "# Accuracy notes",
        "- Streamed API messages appear several times. claudeMon keeps the last copy per message id",
        "- Huge request dumps in transcripts are skipped unread for speed",
        "- Claude Desktop and Cowork usage is visible only through the account limits (tap)",
    ]),
]


def topic_for_page(title):
    for i, t in enumerate(TOPICS):
        if t.get("page") == title:
            return i
    return 0
