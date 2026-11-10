#!/usr/bin/env python3
"""Draw the Activity window from the GitHub GraphQL API.

    GITHUB_TOKEN=... python3 scripts/update_activity.py dist

Run daily by .github/workflows/activity.yml, after Platane/snk has drawn the
contribution snake into dist/snake.svg. Writes dist/activity.svg, which
README.md loads from the `output` branch. Standard library only.

It is one Ghostty-style window in the README hero's look (scripts/terminal.py):
its frame, greys, clay and blue, the embedded JetBrains Mono, and pictures
drawn as ASCII in ghostty.org's brightness ramp. The window is split in three:

- Activity overview: where the past year's contributions went (commits, pull
  requests, code review, issues), as bars of ASCII cells that fill in, and as
  a radar whose shape springs out from the centre while a sweep circles it.
- Contributions: the calendar as ASCII cells in clay, eaten by snk's snake,
  redrawn as a string of Codex-blue glyphs. Without dist/snake.svg the
  calendar is drawn still, from the API.
- TJ-02: a Claude Code-style session replays on a loop. /activity is typed, a
  spinner works, then three tool calls stream their results (a contribution
  summary, the year as a context window filling up, and an omikuji reel that
  spins to today's fortune). On the right, TJ-02 floats in ASCII, as on
  docs/index.html, in the mood the calendar puts it in (the loops are in
  scripts/data, rendered by scripts/build_activity_art.py), and comments in a
  speech bubble; a streak spawns sub-agents and idle days put it to sleep.

With prefers-reduced-motion everything stops on the finished frame.
Only aggregate numbers are used; no repository names are listed.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import random
import re
import sys
import textwrap
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from terminal import (BG, BORDER, CLAUDE, CLAUDE_SHIMMER, CODEX, CREAM, INNER_FONT, MUTED, RAMP, TEXT,
                      TICK, WHITE, fmt, font_css, frame_group, frames_css, layer, mark, shimmer, spans,
                      spinner, text, window)

LOGIN = os.environ.get("GITHUB_REPOSITORY_OWNER", "TakaJun02")
ART_DATA = Path(__file__).resolve().parent / "data" / "tj02-moods.json.gz"

# Spinner verbs in the spirit of Claude Code's, with an agent/RAG twist.
VERBS = [
    "Retrieving", "Reranking", "Embedding", "Chunking", "Orchestrating",
    "Delegating", "Grounding", "Reflecting", "Planning", "Tool-calling",
    "Pondering", "Distilling",
]
LINES = {
    "overclocked": ["{streak}-day streak! Spawned {subs} to keep up.", "{streak} days in a row. My context is on fire."],
    "happy": ["Shipped today. Streak: {streak_days}.", "{today} today. Into the vector store it goes.", "Fresh commits today. Nom nom."],
    "idle": ["No commits since {last}. Feed me a diff?", "Idle since {last}. Polling for pushes..."],
    "sleepy": ["zZ... wake me up when a PR lands.", "{idle} days quiet. Entering low-power mode."],
    "hibernating": ["{idle} days without commits. Hibernating.", "Context compacted. Waiting for commits."],
}
RANKS = ["大吉", "中吉", "小吉", "吉", "末吉", "凶"]
OMIKUJI = [
    ("大吉", "tests pass on the first run"),
    ("大吉", "the retriever nails top-1"),
    ("中吉", "the agent stops exactly when it should"),
    ("中吉", "the reranker agrees with you"),
    ("中吉", "a sub-agent finds the missing doc"),
    ("小吉", "one flaky test, then all green"),
    ("小吉", "the prompt works after one small tweak"),
    ("吉", "everything fits in the context, barely"),
    ("吉", "the embeddings cluster the way you hoped"),
    ("末吉", "merge conflicts, but small ones"),
    ("末吉", "the LLM is confident and mostly right"),
    ("凶", "rate limited until tomorrow"),
    ("凶", "the agent loops; add a stop condition"),
]

GREEN = "#4EBA65"              # Claude Code's success colour, for a finished tool call
# Contribution levels 1-4: denser glyphs in brighter clay. Level 0 is a grey `·`.
LEVEL_GLYPHS = "o+%@"
LEVEL_COLOURS = ("#8E4C35", "#B5603F", "#D77757", "#EB9F7F")
SNAKE_GLYPHS = "@$%*"          # head to tail

# --- Layout ------------------------------------------------------------------------------
W = 1000
X0 = 24                        # left edge of every pane's text
UI = 12.0                      # px, the window's text
UI_CW = UI * 0.6
ART = 8.0                      # px, the ASCII pictures, as in the hero
ART_CW, ART_CH = ART * 0.6, ART * 1.32
A_TOP, A_H = 38, 292           # panes: top and height
B_TOP, B_H = A_TOP + A_H, 196
C_TOP, C_H = B_TOP + B_H, 318
H = C_TOP + C_H

# Activity overview: GitHub's four-axis chart, redrawn as a radar.
AXES = [  # (label, contributionsCollection field, direction from the centre)
    ("Code review", "totalPullRequestReviewContributions", (0, -1)),
    ("Issues", "totalIssueContributions", (1, 0)),
    ("Pull requests", "totalPullRequestContributions", (0, 1)),
    ("Commits", "totalCommitContributions", (-1, 0)),
]
RADAR_X, RADAR_Y, RADAR_R = 756, A_TOP + 158, 82
GROW_AT, GROW_FRAMES = 0.35, 26            # the shape springs out once, on load
SWEEP_FRAMES = 129                         # one turn of the sweep: 4 s
SWEEP_WEDGE = 0.7                          # radians of fading trail behind the sweep
BAR_CELLS, BAR_AT, BAR_STEP = 24, 0.5, 0.03

# Snake: snk draws 53 x 7 cells of 12 px on a 16 px pitch.
SNK_PITCH, SNK_COLS = 16, 53
SNK_FONT = 13

# TJ-02's session (seconds into one replay).
LINE = [C_TOP + 66 + 24 * i for i in range(7)] + [C_TOP + 66 + 24 * 7 + 8]
CYCLE = 22.0
TYPE_AT, PER_KEY = 0.5, 0.09
SPIN_A = (1.45, 2.95)
TOOL1, RES1 = 2.95, 3.4
TOOL2, RES2, FILL_END = 4.3, 4.7, 6.0
TOOL3, RES3, REEL_END = 6.95, 7.35, 9.15
SPIN_B = 10.5
BUBBLE_AT = 10.8
SUBAGENT_AT = 12.2
FADE = (21.2, 21.8)
TJ_X = 884                     # TJ-02's centre

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      commitContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } }
      issueContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } }
      pullRequestContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } }
    }
  }
}
"""


# === Data =================================================================================

def fetch(token: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{LOGIN}-profile-readme",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        body = json.load(res)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]["user"]["contributionsCollection"]


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def streaks(counts: list[int]) -> tuple[int, int]:
    """(current, longest) runs of days with contributions; today may still be empty."""
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    tail = counts[:-1] if counts and counts[-1] == 0 else counts
    current = 0
    for c in reversed(tail):
        if not c:
            break
        current += 1
    return current, longest


def mood_of(idle: int, streak: int) -> str:
    if idle <= 1 and streak >= 5:
        return "overclocked"
    if idle == 0:
        return "happy"
    if idle <= 2:
        return "idle"
    return "sleepy" if idle <= 6 else "hibernating"


def report(calendar: dict) -> dict:
    """Everything TJ-02's session shows, derived from the contribution calendar."""
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days]
    today = date.fromisoformat(days[-1]["date"])
    active = [date.fromisoformat(d["date"]) for d in days if d["contributionCount"]]
    idle = (today - active[-1]).days if active else 999
    streak, longest = streaks(counts)
    rng = random.Random(f"{LOGIN}:{today.isoformat()}")  # stable within a day

    mood = mood_of(idle, streak)
    subagents = min(streak // 2, 2) if mood in ("overclocked", "happy", "idle") else 0
    last = active[-1] if active else today
    message = rng.choice(LINES[mood]).format(
        streak=streak,
        streak_days=plural(streak, "day"),
        subs=plural(subagents, "sub-agent"),
        today=plural(counts[-1], "contribution"),
        last=f"{last:%b} {last.day}",
        idle=idle,
    )
    year_start = date(today.year, 1, 1)
    used = ((today - year_start).days + 1) / (date(today.year + 1, 1, 1) - year_start).days
    rank, fortune = rng.choice(OMIKUJI)
    return {
        "today": today,
        "total": calendar["totalContributions"],
        "summary": f"{plural(calendar['totalContributions'], 'contribution')} · "
                   f"{plural(len(active), 'active day')} · best streak {plural(longest, 'day')}",
        "used": used,
        "rank": rank,
        "fortune": fortune,
        "reel": [rng.choice(RANKS) for _ in range(10)] + [rank],
        "verb": rng.choice(VERBS),
        "mood": mood,
        "message": message,
        "subagents": subagents,
    }


def overview(coll: dict) -> dict:
    """Shares of commits, PRs, reviews and issues, as on GitHub's Activity overview."""
    counts = {label: coll[field] for label, field, _ in AXES}
    total = sum(counts.values())
    repos = {
        entry["repository"]["nameWithOwner"]
        for field in (
            "commitContributionsByRepository", "issueContributionsByRepository",
            "pullRequestContributionsByRepository", "pullRequestReviewContributionsByRepository",
        )
        for entry in coll[field]
    }
    return {
        "counts": counts,
        "pcts": {label: round(n * 100 / total) if total else 0 for label, n in counts.items()},
        "repos": len(repos),
        "private": coll["restrictedContributionsCount"],
    }


# === Drawing helpers ======================================================================

def at(t: float) -> str:
    """A time within the replay as a keyframe offset."""
    return f"{max(0.0, min(t, CYCLE)) / CYCLE * 100:.3f}%"


class Scene:
    """Collects the per-element keyframes of the session's replay."""

    def __init__(self):
        self.css: list[str] = []
        self.count = 0

    def _rule(self, frames: str, style: str = "") -> str:
        self.count += 1
        k = f"k{self.count}"
        self.css.append(f"@keyframes {k}{{{frames}}}.{k}{{{style}animation:{k} {CYCLE}s infinite}}")
        return k

    def appear(self, on: float, off: float | None = None) -> str:
        """Hidden until `on` (and again after `off`) in every replay."""
        if off is None:
            return self._rule(f"0%,{at(on - 0.01)}{{opacity:0}}{at(on)},100%{{opacity:1}}")
        return self._rule(
            f"0%,{at(on - 0.01)}{{opacity:0}}{at(on)},{at(off)}{{opacity:1}}{at(off + 0.01)},100%{{opacity:0}}",
            "opacity:0;",
        )

    def pop(self, on: float, origin: str) -> str:
        """Springs into view at `on`."""
        return self._rule(
            f"0%,{at(on - 0.01)}{{opacity:0;transform:scale(0)}}{at(on)}{{opacity:1;transform:scale(.3)}}"
            f"{at(on + 0.18)}{{transform:scale(1.15)}}{at(on + 0.32)},100%{{opacity:1;transform:scale(1)}}",
            f"transform-box:fill-box;transform-origin:{origin};",
        )

    def typed(self, x: float, y: float, s: str, fill: str, start: float, per: float, size: float = UI) -> str:
        """Text revealed one cell at a time by a background-coloured cover that shrinks away."""
        width = len(s) * size * 0.6
        end = start + len(s) * per
        k = self._rule(
            f"0%,{at(start)}{{transform:scaleX(1);animation-timing-function:steps({len(s)},end)}}"
            f"{at(end)},100%{{transform:scaleX(0)}}",
            "transform:scaleX(0);transform-box:fill-box;transform-origin:right;",
        )
        return (
            text(x, y, s, size, fill, extra=f' textLength="{fmt(width)}" lengthAdjust="spacing"')
            # 1px of slack on the left keeps anti-aliasing from leaking the first glyph;
            # none on the right, so the next glyph never peeks out mid-reveal.
            + f'<rect class="{k}" x="{fmt(x - 1)}" y="{fmt(y - size)}" width="{fmt(width + 1)}" '
            f'height="{fmt(size * 1.45)}" fill="{BG}"/>'
        )

    def tool_dot(self, y: float, on: float, done: float) -> str:
        """Claude Code's tool marker: blinks grey while running, turns green when done."""
        steps = []
        t, lit = on, True
        while t < done - 0.01:
            steps.append(f"{at(t)}{{opacity:{1 if lit else 0.25};fill:{MUTED}}}")
            t, lit = t + 0.22, not lit
        k = self._rule(
            f"0%,{at(on - 0.01)}{{opacity:0;fill:{MUTED}}}{''.join(steps)}"
            f"{at(done)},100%{{opacity:1;fill:{GREEN}}}",
            f"fill:{GREEN};",
        )
        return f'<circle class="{k}" cx="{X0 + 6}" cy="{fmt(y - 4)}" r="4"/>'


def pane_header(top: float, label: str, meta: str) -> str:
    """A pane's first line: Claude Code's ✻, a name, and a note on the right."""
    y = top + 28
    return (mark(X0 + UI_CW / 2, y - UI * 0.36, 0.62) + text(X0 + 2 * UI_CW, y, label, UI, TEXT)
            + text(W - X0, y, meta, 11, MUTED, anchor="end"))


def art_text(rows: list[str], cells: str, cls: str) -> str:
    """ASCII rows as one <text> in the 10 px inner grid (see terminal.layer)."""
    return f'<text class="{cls}">{layer(rows, cells)}</text>'


def art_group(x: float, y: float, body: str) -> str:
    return (f'<g transform="translate({fmt(x)} {fmt(y)}) scale({fmt(ART / INNER_FONT)})" '
            f'font-size="{INNER_FONT}">{body}</g>')


# === Activity overview ====================================================================

def bar(x: float, y: float, pct: int, start: float) -> str:
    """A bar of ASCII cells; its cells turn from `·` to `$` one by one."""
    fill = pct / 100 * BAR_CELLS
    full = int(fill)
    cells = [RAMP[8]] * full
    if full < BAR_CELLS and fill - full >= 0.15:
        cells.append(RAMP[max(1, int((fill - full) * 8))])     # the end of the bar, partly lit
    out = []
    rest = BAR_CELLS - len(cells)
    if rest:
        out.append(text(x + len(cells) * UI_CW, y, "·" * rest, UI, BORDER))
    for k, g in enumerate(cells):
        d = f' style="animation-delay:{start + k * BAR_STEP:.2f}s"'
        out.append(text(x + k * UI_CW, y, "·", UI, BORDER, extra=f' class="off"{d}'))
        out.append(text(x + k * UI_CW, y, g, UI, CLAUDE, extra=f' class="on"{d}'))
    return "".join(out)


def inside(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def radar(o: dict) -> tuple[str, str]:
    """The radar in ASCII: dotted rings and axes, the shape in clay, the corners in cream."""
    pcts = o["pcts"]
    peak = max(pcts.values()) or 1      # like GitHub, the largest share reaches the axis end
    R = RADAR_R
    cols, rows = int((2 * R + 30) / ART_CW) | 1, int((2 * R + 26) / ART_CH) | 1
    gx0, gy0 = RADAR_X - cols * ART_CW / 2, RADAR_Y - rows * ART_CH / 2
    centres = [[(gx0 + (c + 0.5) * ART_CW - RADAR_X, gy0 + (r + 0.5) * ART_CH - RADAR_Y)
                for c in range(cols)] for r in range(rows)]

    # Rings at half and full radius and the axes through the centre, in `·`.
    grid = [[" "] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            dx, dy = centres[r][c]
            d = math.hypot(dx, dy)
            reach = (abs(dx) * ART_CW + abs(dy) * ART_CH) / (2 * max(d, 1e-9))
            on_ring = any(abs(d - f * R) < reach * 0.75 for f in (0.5, 1.0))
            on_axis = (abs(dx) < ART_CW / 2 and abs(dy) <= R) or (abs(dy) < ART_CH / 2 and abs(dx) <= R)
            if on_ring or on_axis:
                grid[r][c] = "K"

    def shape(s: float) -> list[list[str]]:
        """The data's polygon at `s` times its size, as cells: A-J by coverage, j at the corners.
        Unlike the characters, partly covered cells keep a faint glyph, so the
        thin corners still reach their points."""
        poly = [(dx * R * pcts[label] / peak * s, dy * R * pcts[label] / peak * s) for label, _, (dx, dy) in AXES]
        out = [[" "] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                cx, cy = centres[r][c]
                hits = sum(inside(cx + (i - 1) * ART_CW / 3, cy + (j - 2.5) * ART_CH / 6, poly)
                           for i in range(3) for j in range(6))
                if hits >= 2:
                    out[r][c] = "ABCDEFGHIJ"[min(8, round(hits / 18 * 8))]
        for (label, _, _), (px, py) in zip(AXES, poly):
            if pcts[label]:
                c, r = int((px + RADAR_X - gx0) // ART_CW), int((py + RADAR_Y - gy0) // ART_CH)
                if 0 <= r < rows and 0 <= c < cols:
                    out[r][c] = "j"
        return out

    def as_rows(g):
        return ["".join(row) for row in g]

    layers = [("ABCDEFGHIJ", "rp"), ("_________j", "rv")]

    def picture(g):
        return "".join(art_text(as_rows(g), cells, cls) for cells, cls in layers)

    # Springs out from the centre: one frame a tick, then the final shape stays.
    grow = []
    for i in range(GROW_FRAMES):
        t = (i + 1) * TICK
        s = 1 - math.exp(-5.5 * t) * math.cos(8.5 * t)
        grow.append(f'<g class="gr" style="animation-delay:{GROW_AT + i * TICK:.3f}s">{picture(shape(s))}</g>')
    final = shape(1.0)
    grow.append(f'<g class="gf" style="animation-delay:{GROW_AT + GROW_FRAMES * TICK:.3f}s">{picture(final)}</g>')

    # The sweep: a fading trail behind a line that turns clockwise from the top,
    # drawn only in empty cells, so the rings and the shape stay crisp.
    sweep = []
    for k in range(SWEEP_FRAMES):
        theta = 2 * math.pi * k / SWEEP_FRAMES
        g = [[" "] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                dx, dy = centres[r][c]
                if math.hypot(dx, dy) > R + 4 or grid[r][c] != " " or final[r][c] != " ":
                    continue
                phi = math.atan2(dx, -dy) % (2 * math.pi)             # clockwise from the top
                behind = (theta - phi) % (2 * math.pi)
                if behind < SWEEP_WEDGE:
                    g[r][c] = "B" if behind < 0.12 else "A"                 # a `~` edge, a `·` trail
        sweep.append(frame_group(as_rows(g), [("ABCDEFGHIJ", "rs")], None, "sw", k * TICK))

    body = art_text(as_rows(grid), "K", "rg") + "".join(sweep) + "".join(grow)
    css = (frames_css("sw", SWEEP_FRAMES)
           + f".gr{{visibility:hidden;animation:gr {TICK}s step-end forwards}}"
           f"@keyframes gr{{0%{{visibility:visible}}100%{{visibility:hidden}}}}"
           ".gf{visibility:hidden;animation:gf 0s forwards}@keyframes gf{to{visibility:visible}}"
           f".rp{{fill:{CLAUDE}}}.rv{{fill:{CREAM}}}.rg{{fill:{BORDER}}}.rs{{fill:{CLAUDE};opacity:.55}}")

    def axis_label(label: str, x: float, y: float, anchor: str) -> str:
        pct = pcts[label]
        lines = ([(f"{pct}%", WHITE)] if pct else []) + [(label, MUTED)]
        return "".join(text(x, y + i * 16, s, UI, fill, anchor=anchor) for i, (s, fill) in enumerate(lines))

    def side(label: str) -> float:  # one or two lines sit centred on the axis
        return RADAR_Y - 4 if pcts[label] else RADAR_Y + 4

    labels = (
        axis_label("Code review", RADAR_X, RADAR_Y - R - 16 - (16 if pcts["Code review"] else 0), "middle")
        + axis_label("Issues", RADAR_X + R + 18, side("Issues"), "start")
        + axis_label("Pull requests", RADAR_X, RADAR_Y + R + 22, "middle")
        + axis_label("Commits", RADAR_X - R - 18, side("Commits"), "end")
    )
    return art_group(gx0, gy0, body) + labels, css


def overview_pane(o: dict) -> tuple[str, str]:
    top = A_TOP
    counts, pcts = o["counts"], o["pcts"]
    repos_text = f"{o['repos']:,} {'repository' if o['repos'] == 1 else 'repositories'}"
    out = [pane_header(top, "Activity overview", "past year"),
           spans(X0, top + 64, [("Contributed to ", TEXT), (repos_text, WHITE)], UI)]
    if o["private"]:
        out.append(text(X0, top + 84, f"plus {plural(o['private'], 'private contribution')}", 11, MUTED))
    for i, (label, _, _) in enumerate(sorted(AXES, key=lambda a: -counts[a[0]])):
        y = top + 140 + i * 32
        bx = X0 + 20 * UI_CW
        out.append(text(X0, y, label, UI, TEXT))
        out.append(text(X0 + 18 * UI_CW, y, f"{counts[label]:,}", UI, MUTED, anchor="end"))
        out.append(bar(bx, y, pcts[label], BAR_AT + i * 0.12))
        out.append(text(bx + (BAR_CELLS + 5) * UI_CW, y, f"{pcts[label]}%", UI, WHITE if pcts[label] else MUTED,
                        anchor="end"))
    out.append(f'<path d="M520 {top + 48}V{top + A_H - 18}" stroke="{BORDER}"/>')
    pic, css = radar(o)
    out.append(pic)
    css += (".on{opacity:0;animation:on .01s linear both}@keyframes on{from{opacity:0}to{opacity:1}}"
            ".off{animation:off .01s linear both}@keyframes off{from{opacity:1}to{opacity:0}}")
    return "".join(out), css


# === Contributions ========================================================================

def cell_glyph(x: float, y: float, glyph: str, attrs: str = "") -> str:
    """A glyph centred in a snk cell whose top-left is (x, y)."""
    return f'<text x="{fmt(x + 6)}" y="{fmt(y + 6 + SNK_FONT * 0.36)}"{attrs}>{glyph}</text>'


def snake_layers(svg: str) -> tuple[str, str] | None:
    """snk's animation with its cells and snake redrawn as glyphs. snk colours a
    cell by level and turns it to --ce once eaten; here --ce is transparent, so
    an eaten cell falls back to the grey `·` under it."""
    style = re.search(r"<style>(.*?)</style>", svg, re.S)
    if not style:
        return None
    css = style.group(1)
    levels = dict(re.findall(r"\.c\.(\w+)\{fill:var\(--c(\d)\)", css))
    cells = re.findall(r'<rect class="c(?: (\w+))?" x="([\d.]+)" y="([\d.]+)"', svg)
    segments = re.findall(r'<rect class="s (s\d+)"', svg)
    if not cells or not segments:
        return None
    dots = {}
    glyphs = []
    for cls, x, y in cells:
        x, y = float(x), float(y)
        dots.setdefault(y, []).append(x)
        if cls and cls in levels:
            lv = int(levels[cls])
            glyphs.append(cell_glyph(x, y, LEVEL_GLYPHS[lv - 1], f' class="c {cls}"'))
    track = "".join(f'<text x="{" ".join(fmt(x + 6) for x in xs)}" y="{fmt(y + 6 + SNK_FONT * 0.36)}">'
                    f'{"·" * len(xs)}</text>' for y, xs in sorted(dots.items()))
    snake = "".join(f'<g class="s {cls}"><rect width="{SNK_PITCH}" height="{SNK_PITCH}" fill="{BG}"/>'
                    f'{cell_glyph(2, 2, SNAKE_GLYPHS[min(i, 3)])}</g>' for i, cls in enumerate(segments))
    colours = ";".join(f"--c{i + 1}:{c}" for i, c in enumerate(LEVEL_COLOURS))
    body = (f'<g fill="{BORDER}">{track}</g>'
            f'<g style="--ce:transparent;--cb:transparent;--cs:{CODEX};{colours}">{"".join(glyphs)}{snake}</g>')
    css = re.sub(r":root\{[^}]*\}", "", css) + ".c{stroke:none}.u{display:none}"
    return body, css


def still_calendar(calendar: dict) -> str:
    """The calendar without the snake, from the API."""
    level = {"FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    out = []
    for w, week in enumerate(calendar["weeks"][-SNK_COLS:]):
        for day in week["contributionDays"]:
            d = date.fromisoformat(day["date"]).isoweekday() % 7      # Sunday first, as on GitHub
            x, y = 2 + w * SNK_PITCH, 2 + d * SNK_PITCH
            lv = level.get(day.get("contributionLevel"), 0)
            out.append(cell_glyph(x, y, LEVEL_GLYPHS[lv - 1] if lv else "·",
                                  f' fill="{LEVEL_COLOURS[lv - 1] if lv else BORDER}"'))
    return "".join(out)


def calendar_pane(r: dict, calendar: dict, snake_svg: str | None) -> tuple[str, str]:
    top = B_TOP
    k = (W - 2 * X0) / (SNK_COLS * SNK_PITCH)
    layers = snake_layers(snake_svg) if snake_svg else None
    body, css = layers if layers else (still_calendar(calendar), "")
    meta = f"{plural(r['total'], 'contribution')} in the past year"
    out = (pane_header(top, "Contributions", meta)
           + f'<g transform="translate({X0} {top + 54}) scale({fmt(k)})" font-size="{SNK_FONT}" '
           f'text-anchor="middle">{body}</g>')
    return out, css


# === TJ-02's session ======================================================================

def bubble_path(bx: float, by: float, bw: float, bh: float, tail_y: float) -> str:
    """A rounded box with a tail on its right, pointing at TJ-02."""
    rad = 7
    return (
        f"M{fmt(bx + rad)} {fmt(by)}H{fmt(bx + bw - rad)}A{rad} {rad} 0 0 1 {fmt(bx + bw)} {fmt(by + rad)}"
        f"V{fmt(tail_y - 6)}L{fmt(bx + bw + 10)} {fmt(tail_y + 2)}L{fmt(bx + bw)} {fmt(tail_y + 4)}"
        f"V{fmt(by + bh - rad)}A{rad} {rad} 0 0 1 {fmt(bx + bw - rad)} {fmt(by + bh)}"
        f"H{fmt(bx + rad)}A{rad} {rad} 0 0 1 {fmt(bx)} {fmt(by + bh - rad)}V{fmt(by + rad)}"
        f"A{rad} {rad} 0 0 1 {fmt(bx + rad)} {fmt(by)}Z"
    )


def ascii_loop(frames: list[str], x: float, y: float, prefix: str, offset: int = 0) -> str:
    """A 240-frame loop of TJ-02: the body in cream, the clay accents and outline in clay."""
    groups = []
    n = len(frames)
    for i, f in enumerate(frames):
        rows = f.split("\n")
        fid = f"{prefix}{i}" if i == offset else None       # the frame shown with reduced motion
        groups.append(frame_group(rows, [(RAMP, "tb"), ("ABCDEFGHIJ", "ta")], fid, "tf", ((i - offset) % n) * TICK))
    return art_group(x, y, "".join(groups))


def session_pane(s: Scene, r: dict, art: dict) -> tuple[str, str]:
    top = C_TOP
    y = LINE
    out = [pane_header(top, "TJ-02 · daily activity report", f"updated {r['today'].isoformat()}")]
    css = []

    # > /activity, typed with a moving cursor, then submitted.
    typed_end = TYPE_AT + 9 * PER_KEY
    cursor = s._rule(
        f"0%,{at(TYPE_AT)}{{opacity:1;transform:translateX(0);animation-timing-function:steps(9,end)}}"
        f"{at(typed_end)},{at(typed_end + 0.25)}{{opacity:1;transform:translateX({fmt(9 * UI_CW)}px)}}"
        f"{at(typed_end + 0.26)},100%{{opacity:0;transform:translateX({fmt(9 * UI_CW)}px)}}",
        "opacity:0;",
    )
    replay = [text(X0, y[0], ">", UI, MUTED),
              s.typed(X0 + 2 * UI_CW, y[0], "/activity", WHITE, TYPE_AT, PER_KEY),
              f'<rect class="{cursor}" x="{fmt(X0 + 2 * UI_CW)}" y="{y[0] - 11}" width="{fmt(UI_CW)}" height="15" fill="{TEXT}"/>']

    def working(row: int, verb: str, sid: str, on: float, off: float | None) -> str:
        """Claude Code's status line: the spinner, the verb shimmering, and the hint."""
        sp, sp_css = spinner(X0 + UI_CW / 2, y[row] - UI * 0.36, 0.62, CLAUDE, prefix=sid)
        word, word_css = shimmer(f"{sid}h", X0 + 2 * UI_CW, y[row], verb, UI, CLAUDE, CLAUDE_SHIMMER, 2.4)
        css.extend([sp_css, word_css])
        rest = text(X0 + (2 + len(verb)) * UI_CW, y[row], " (esc to interrupt)", UI, MUTED)
        return f'<g class="{s.appear(on, off)}">{sp}{word}{rest}</g>'

    def call(row: int, name: str, args: str, on: float) -> str:
        return (f'<g class="{s.appear(on)}">'
                + spans(X0 + 2 * UI_CW, y[row], [(name, WHITE), (f"({args})", MUTED)], UI) + "</g>")

    def elbow(row: int, on: float) -> str:
        yy = y[row]
        return (f'<path class="{s.appear(on)}" d="M{fmt(X0 + 2 * UI_CW + 2)} {yy - 15}V{yy - 5}H{fmt(X0 + 4 * UI_CW)}" '
                f'stroke="{MUTED}" stroke-width="1.2" fill="none"/>')

    tx = X0 + 5 * UI_CW                      # the results' column
    replay.append(working(1, "Retrieving…", "qa", *SPIN_A))

    # 1. Contributions
    replay += [s.tool_dot(y[1], TOOL1, RES1 + 0.6), call(1, "Contributions", "past year", TOOL1), elbow(2, RES1),
               s.typed(tx, y[2], r["summary"], TEXT, RES1, 0.011)]

    # 2. Context window: the year as ASCII cells that light up one by one.
    filled = round(r["used"] * 20)
    replay += [s.tool_dot(y[3], TOOL2, FILL_END + 0.6), call(3, "Context", str(r["today"].year), TOOL2), elbow(4, RES2)]
    for i in range(20):
        cx = tx + i * UI_CW
        if i < filled:
            t = RES2 + (FILL_END - RES2) * (i + 1) / filled
            replay.append(text(cx, y[4], "·", UI, BORDER, extra=f' class="{s.appear(RES2, t)}"'))
            replay.append(text(cx, y[4], RAMP[8], UI, CLAUDE, extra=f' class="{s.appear(t)}"'))
        else:
            replay.append(text(cx, y[4], "·", UI, BORDER, extra=f' class="{s.appear(RES2)}"'))
    caption = f"{round(r['used'] * 100)}% used · auto-compact on Jan 1"
    replay.append(s.typed(tx + 21 * UI_CW, y[4], caption, MUTED, FILL_END + 0.05, 0.018))

    # 3. Omikuji: a slot reel spins and lands on today's rank.
    replay += [s.tool_dot(y[5], TOOL3, REEL_END), call(5, "Omikuji", "today", TOOL3), elbow(6, RES3)]
    box_x, box_w, step = tx, 40, 20
    shift = (len(r["reel"]) - 1) * step
    reel = s._rule(
        f"0%,{at(RES3)}{{transform:translateY(0);animation-timing-function:cubic-bezier(.12,.75,.2,1)}}"
        f"{at(REEL_END)},100%{{transform:translateY(-{shift}px)}}",
        f"transform:translateY(-{shift}px);",
    )
    items = "".join(text(box_x + box_w / 2, y[6] + j * step, rank, UI, CLAUDE, anchor="middle", check=False)
                    for j, rank in enumerate(r["reel"]))
    replay.append(
        f'<g class="{s.appear(RES3)}"><clipPath id="reel"><rect x="{fmt(box_x)}" y="{y[6] - 15}" '
        f'width="{box_w}" height="{step}"/></clipPath>'
        f'<rect x="{fmt(box_x)}" y="{y[6] - 15}" width="{box_w}" height="{step}" rx="4" fill="none" '
        f'stroke="{CLAUDE}"/><g clip-path="url(#reel)"><g class="{reel}">{items}</g></g></g>'
    )
    replay.append(s.typed(box_x + box_w + 10, y[6], r["fortune"], TEXT, REEL_END + 0.05, 0.022))

    # The closing spinner keeps working until the replay starts over.
    replay.append(working(7, f"{r['verb']}…", "qb", SPIN_B, None))

    # TJ-02, floating in its mood.
    frames = art["moods"][r["mood"]]
    rows = frames[0].split("\n")
    tw, th = max(len(row) for row in rows) * ART_CW, len(rows) * ART_CH
    tj_x, tj_y = TJ_X - tw / 2, top + C_H - 26 - th
    out.append(ascii_loop(frames, tj_x, tj_y, "tf"))
    out.append(text(TJ_X, top + C_H - 14, "TJ-02", 11, MUTED, anchor="middle"))
    if r["mood"] in ("sleepy", "hibernating"):
        out += [text(tj_x + tw - 18 + i * 5, tj_y + 40 - i * 4, "z", 12 + i * 2, MUTED,
                     extra=f' class="z" style="animation-delay:-{i}s"')
                for i in range(3 if r["mood"] == "hibernating" else 2)]

    # Its speech bubble, to its left, with the text typed in.
    lines = textwrap.wrap(r["message"], 26)
    bw = max(len(line) for line in lines) * UI_CW + 24
    bh = len(lines) * 18 + 16
    bx, by = tj_x - 14 - bw, tj_y + 36
    t = BUBBLE_AT + 0.25
    texts = []
    for i, line in enumerate(lines):
        texts.append(s.typed(bx + 12, by + 22 + i * 18, line, TEXT, t, 0.035))
        t += len(line) * 0.035 + 0.1
    replay.append(f'<g class="{s.pop(BUBBLE_AT, "right center")}"><path d="{bubble_path(bx, by, bw, bh, by + bh / 2)}" '
                  f'fill="{BG}" stroke="{CLAUDE}"/>{"".join(texts)}</g>')

    # Sub-agents: one per two days of streak, under the bubble, each popping in.
    mini = art["mini"]
    mrows = mini[0].split("\n")
    mw, mh = max(len(row) for row in mrows) * ART_CW, len(mrows) * ART_CH
    for i in range(r["subagents"]):
        mx = bx + bw - (i + 1) * (mw + 12)
        my = tj_y + th - mh
        replay.append(f'<g class="{s.pop(SUBAGENT_AT + i * 0.3, "center bottom")}">'
                      f'{ascii_loop(mini, mx, my, f"m{i}f", offset=80 * i)}</g>')

    out.append(f'<g class="replay">{"".join(replay)}</g>')
    css.append(f"@keyframes replay{{0%,{at(FADE[0])}{{opacity:1}}{at(FADE[1])},100%{{opacity:0}}}}"
               f".replay{{animation:replay {CYCLE}s infinite}}"
               + frames_css("tf", len(frames))
               + f".tb{{fill:{CREAM}}}.ta{{fill:{CLAUDE}}}"
               ".z{opacity:0;animation:zfloat 3s ease-out infinite}"
               "@keyframes zfloat{0%{opacity:0;transform:translate(0,0)}20%{opacity:1}"
               "100%{opacity:0;transform:translate(10px,-26px)}}")
    return "".join(out), "".join(css)


# === The window ===========================================================================

def build(r: dict, o: dict, calendar: dict, art: dict, snake_svg: str | None) -> str:
    s = Scene()
    a, a_css = overview_pane(o)
    b, b_css = calendar_pane(r, calendar, snake_svg)
    c, c_css = session_pane(s, r, art)
    summary = "; ".join(f"{label} {o['pcts'][label]}%" for label, _, _ in AXES)
    desc = (
        f"Activity for the past year: {summary}; {r['summary']}. A contribution snake eats the calendar. "
        f"TJ-02's session: {round(r['used'] * 100)}% of {r['today'].year} used, auto-compacting on Jan 1; "
        f"today's omikuji: {r['rank']}, {r['fortune']}. TJ-02 is {r['mood']} and says: {r['message']}"
    )
    css = [
        font_css(), a_css, b_css, c_css, "".join(s.css),
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}"
        ".gf,#tf0,#m0f0,#m1f80,#m2f160,#qa0,#qb0{visibility:visible}.on,.z{opacity:1}.off{opacity:0}}",
    ]
    divider = "".join(f'<path d="M1 {y}H{W - 1}" stroke="{BORDER}"/>' for y in (B_TOP, C_TOP))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'xml:space="preserve" role="img" aria-labelledby="title desc">'
        f'<title id="title">TakaJun02\'s activity</title><desc id="desc">{escape(desc)}</desc>'
        "<!-- Generated by scripts/update_activity.py. TJ-02 is rendered by scripts/build_activity_art.py; the snake\n"
        "     is Platane/snk's (MIT). Text is set in a subset of JetBrains Mono, Copyright 2020 The JetBrains Mono\n"
        "     Project Authors, SIL Open Font License 1.1. -->"
        f"<style>{''.join(css)}</style>"
        + window(W, H, "activity") + divider + a + b + c + "</svg>"
    )


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    out.mkdir(parents=True, exist_ok=True)
    coll = fetch(token)
    calendar = coll["contributionCalendar"]
    r, o = report(calendar), overview(coll)
    art = json.loads(gzip.decompress(ART_DATA.read_bytes()))
    snake = out / "snake.svg"
    snake_svg = snake.read_text(encoding="utf-8") if snake.exists() else None
    path = out / "activity.svg"
    path.write_text(build(r, o, calendar, art, snake_svg), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size:,} bytes) · mood={r['mood']} · overview={o['pcts']}"
          f" · snake={'yes' if snake_svg and snake_layers(snake_svg) else 'no'}")


if __name__ == "__main__":
    main()
