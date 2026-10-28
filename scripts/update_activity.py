#!/usr/bin/env python3
"""Draw the Activity section's animated SVGs from the GitHub GraphQL API.

    GITHUB_TOKEN=... python3 scripts/update_activity.py dist

Run daily by .github/workflows/activity.yml, which publishes dist/ (together
with the contribution snake) to the `output` branch that README.md loads its
Activity images from. Standard library only. Two cards, each in dark/light:

overview-*.svg redraws GitHub's Activity overview (shares of commits, pull
requests, code review and issues) as a radar: the shape springs out from the
centre, a sweep circles it, and the data points ping.

activity-*.svg replays a Claude Code-style session on a loop: /activity is typed, a
spinner works, then three tool calls stream their results (a contribution
summary, the year as a context window filling up, and an omikuji reel that
spins to today's fortune). On the right, TJ-02, a small agent whose mood
follows the contribution calendar, comments in a speech bubble; a streak
spawns bouncing sub-agents and idle days put it to sleep.

Animation is CSS (plus one SMIL gradient for the shimmer). With
prefers-reduced-motion everything stops on the finished frame.
Only aggregate numbers are used; no repository names are listed.
"""

from __future__ import annotations

import json
import os
import random
import sys
import textwrap
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

LOGIN = os.environ.get("GITHUB_REPOSITORY_OWNER", "TakaJun02")

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

THEMES = {
    "dark": {
        "bg": "#1C1B19", "border": "#33312D", "text": "#E8E6DE", "dim": "#8E8C84",
        "accent": "#D97757", "glow": "#FFD9C7", "green": "#6CC07A", "track": "#33312D",
    },
    "light": {
        "bg": "#FBFAF7", "border": "#E6E2D8", "text": "#1F1E1D", "dim": "#75736C",
        "accent": "#C8643F", "glow": "#F7C9B4", "green": "#2F8F46", "track": "#E6E2D8",
    },
}
MONO = (
    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, '
    '"Liberation Mono", "DejaVu Sans Mono", monospace'
)

# Canvas (viewBox units): transcript on the left, TJ-02 on the right.
W, H = 840, 270
X0 = 24                      # left edge of the transcript
LINE = [70, 94, 118, 142, 166, 190, 214, 246]
FONT, CELL = 14, 14 * 0.6
BOT_X, BOT_Y = 660, 150      # TJ-02's head: centre x, top y

# One replay of the session (seconds).
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

# Activity overview: GitHub's four-axis chart, redrawn as a radar.
OVERVIEW_H = 300
AXES = [  # (label, contributionsCollection field, direction from the centre)
    ("Code review", "totalPullRequestReviewContributions", (0, -1)),
    ("Issues", "totalIssueContributions", (1, 0)),
    ("Pull requests", "totalPullRequestContributions", (0, 1)),
    ("Commits", "totalCommitContributions", (-1, 0)),
]
RADAR_X, RADAR_Y, RADAR_R = 630, 168, 76

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
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
    """Everything the scene shows, derived from the contribution calendar."""
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days]
    today = date.fromisoformat(days[-1]["date"])
    active = [date.fromisoformat(d["date"]) for d in days if d["contributionCount"]]
    idle = (today - active[-1]).days if active else 999
    streak, longest = streaks(counts)
    rng = random.Random(f"{LOGIN}:{today.isoformat()}")  # stable within a day

    mood = mood_of(idle, streak)
    subagents = min(streak // 2, 3) if mood in ("overclocked", "happy", "idle") else 0
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


def num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def at(t: float) -> str:
    """A time within the replay as a keyframe offset."""
    return f"{max(0.0, min(t, CYCLE)) / CYCLE * 100:.3f}%"


class Scene:
    """Collects SVG markup and the per-element keyframes of one replay."""

    def __init__(self, theme: dict):
        self.c = theme
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

    def typed(self, x: float, y: float, text: str, size: float, fill: str, start: float, per: float) -> str:
        """Text revealed one cell at a time by a background-coloured cover that shrinks away."""
        width = len(text) * size * 0.6
        end = start + len(text) * per
        k = self._rule(
            f"0%,{at(start)}{{transform:scaleX(1);animation-timing-function:steps({len(text)},end)}}"
            f"{at(end)},100%{{transform:scaleX(0)}}",
            "transform:scaleX(0);transform-box:fill-box;transform-origin:right;",
        )
        return (
            f'<text x="{num(x)}" y="{num(y)}" font-size="{num(size)}" fill="{fill}" '
            f'textLength="{num(width)}" lengthAdjust="spacing">{escape(text)}</text>'
            # 1px of slack on the left keeps anti-aliasing from leaking the first glyph;
            # none on the right, so the next glyph never peeks out mid-reveal.
            f'<rect class="{k}" x="{num(x - 1)}" y="{num(y - size)}" width="{num(width + 1)}" '
            f'height="{num(size * 1.45)}" fill="{self.c["bg"]}"/>'
        )

    def tool_dot(self, y: float, on: float, done: float) -> str:
        """Claude Code's tool marker: blinks while running, turns green when done."""
        c = self.c
        steps = []
        t, lit = on, True
        while t < done - 0.01:
            steps.append(f"{at(t)}{{opacity:{1 if lit else 0.25};fill:{c['dim']}}}")
            t, lit = t + 0.22, not lit
        k = self._rule(
            f"0%,{at(on - 0.01)}{{opacity:0;fill:{c['dim']}}}{''.join(steps)}"
            f"{at(done)},100%{{opacity:1;fill:{c['green']}}}",
            f"fill:{c['green']};",
        )
        return f'<circle class="{k}" cx="{X0 + 6}" cy="{num(y - 5)}" r="4"/>'


def star(cx: float, cy: float, r: float, cls: str, color: str, width: float = 1.6) -> str:
    k = r * 0.7071
    d = (
        f"M{num(cx - r)} {num(cy)}H{num(cx + r)}M{num(cx)} {num(cy - r)}V{num(cy + r)}"
        f"M{num(cx - k)} {num(cy - k)}L{num(cx + k)} {num(cy + k)}"
        f"M{num(cx - k)} {num(cy + k)}L{num(cx + k)} {num(cy - k)}"
    )
    return f'<path class="{cls}" d="{d}" stroke="{color}" stroke-width="{width}" stroke-linecap="round" fill="none"/>'


def transcript(s: Scene, r: dict) -> str:
    c = s.c
    out: list[str] = []
    y = LINE

    # > /activity, typed with a moving cursor, then submitted.
    typed_end = TYPE_AT + 9 * PER_KEY
    cursor = s._rule(
        f"0%,{at(TYPE_AT)}{{opacity:1;transform:translateX(0);animation-timing-function:steps(9,end)}}"
        f"{at(typed_end)},{at(typed_end + 0.25)}{{opacity:1;transform:translateX({num(9 * CELL)}px)}}"
        f"{at(typed_end + 0.26)},100%{{opacity:0;transform:translateX({num(9 * CELL)}px)}}",
        "opacity:0;",
    )
    out.append(f'<text x="{X0}" y="{y[0]}" fill="{c["accent"]}">&gt;</text>')
    out.append(s.typed(X0 + 18, y[0], "/activity", FONT, c["text"], TYPE_AT, PER_KEY))
    out.append(f'<rect class="{cursor}" x="{X0 + 18}" y="{y[0] - 13}" width="{num(CELL - 1.5)}" height="17" fill="{c["text"]}"/>')

    # A first spinner while the agent "works".
    spin_a = s.appear(*SPIN_A)
    out.append(
        f'<g class="{spin_a}">{star(X0 + 6, y[1] - 5, 5, "twinkle", c["accent"])}'
        f'<text x="{X0 + 18}" y="{y[1]}"><tspan class="shimmer">Retrieving…</tspan>'
        f'<tspan fill="{c["dim"]}"> (esc to interrupt)</tspan></text></g>'
    )

    def call(row: int, name: str, args: str, on: float) -> str:
        k = s.appear(on)
        return (
            f'<text class="{k}" x="{X0 + 18}" y="{y[row]}" fill="{c["text"]}">'
            f'<tspan font-weight="700">{escape(name)}</tspan><tspan fill="{c["dim"]}">({escape(args)})</tspan></text>'
        )

    def elbow(row: int, on: float) -> str:
        k = s.appear(on)
        yy = y[row]
        return (
            f'<path class="{k}" d="M{X0 + 18} {yy - 14}V{yy - 5}H{X0 + 27}" stroke="{c["dim"]}" '
            f'stroke-width="1.3" fill="none"/>'
        )

    tx = X0 + 34  # result text column

    # 1. Contributions
    out += [s.tool_dot(y[1], TOOL1, RES1 + 0.6), call(1, "Contributions", "past year", TOOL1), elbow(2, RES1)]
    out.append(s.typed(tx, y[2], r["summary"], FONT, c["text"], RES1, 0.011))

    # 2. Context window: cells light up one by one, then the caption streams in.
    filled = round(r["used"] * 20)
    out += [s.tool_dot(y[3], TOOL2, FILL_END + 0.6), call(3, "Context", str(r["today"].year), TOOL2), elbow(4, RES2)]
    cells = [f'<g class="{s.appear(RES2)}">']
    for i in range(20):
        cells.append(f'<rect x="{num(tx + i * 8.4)}" y="{y[4] - 11}" width="7" height="11" rx="1.5" fill="{c["track"]}"/>')
    cells.append("</g>")
    for i in range(filled):
        t = RES2 + (FILL_END - RES2) * (i + 1) / filled
        cells.append(
            f'<rect class="{s.appear(t)}" x="{num(tx + i * 8.4)}" y="{y[4] - 11}" width="7" height="11" '
            f'rx="1.5" fill="{c["accent"]}"/>'
        )
    out += cells
    caption = f"{round(r['used'] * 100)}% used · auto-compact on Jan 1"
    out.append(s.typed(tx + 20 * 8.4 + 8, y[4], caption, FONT, c["dim"], FILL_END + 0.05, 0.018))

    # 3. Omikuji: a slot reel spins and lands on today's rank.
    out += [s.tool_dot(y[5], TOOL3, REEL_END), call(5, "Omikuji", "today", TOOL3), elbow(6, RES3)]
    box_x, box_w, step = tx, 40, 20
    shift = (len(r["reel"]) - 1) * step
    reel = s._rule(
        f"0%,{at(RES3)}{{transform:translateY(0);animation-timing-function:cubic-bezier(.12,.75,.2,1)}}"
        f"{at(REEL_END)},100%{{transform:translateY(-{shift}px)}}",
        f"transform:translateY(-{shift}px);",
    )
    items = "".join(
        f'<text x="{box_x + box_w / 2}" y="{y[6] + j * step}" text-anchor="middle" fill="{c["accent"]}" '
        f'font-weight="700">{escape(rank)}</text>'
        for j, rank in enumerate(r["reel"])
    )
    out.append(
        f'<g class="{s.appear(RES3)}"><clipPath id="reel"><rect x="{box_x}" y="{y[6] - 16}" '
        f'width="{box_w}" height="{step}"/></clipPath>'
        f'<rect x="{box_x}" y="{y[6] - 16}" width="{box_w}" height="{step}" rx="4" fill="none" '
        f'stroke="{c["accent"]}" stroke-width="1"/>'
        f'<g clip-path="url(#reel)"><g class="{reel}">{items}</g></g></g>'
    )
    out.append(s.typed(box_x + box_w + 10, y[6], f"— {r['fortune']}", FONT, c["text"], REEL_END + 0.05, 0.022))

    # The closing spinner keeps working until the replay starts over.
    spin_b = s.appear(SPIN_B)
    out.append(
        f'<g class="{spin_b}">{star(X0 + 6, y[7] - 5, 5, "twinkle", c["accent"])}'
        f'<text x="{X0 + 18}" y="{y[7]}"><tspan class="shimmer">{escape(r["verb"])}…</tspan>'
        f'<tspan fill="{c["dim"]}"> (esc to interrupt)</tspan></text></g>'
    )
    return "\n  ".join(out)


def tj02(s: Scene, r: dict) -> tuple[str, str]:
    """TJ-02 itself (always on stage) and its bubble and sub-agents (part of each replay)."""
    c, mood = s.c, r["mood"]
    cx, hy = BOT_X, BOT_Y
    ey, my = hy + 21, hy + 35
    ink = f'stroke="{c["text"]}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"'

    eyes = {
        "happy": "".join(f'<path d="M{x - 5} {ey + 2}L{x} {ey - 3}L{x + 5} {ey + 2}" {ink}/>' for x in (cx - 14, cx + 14)),
        "overclocked": "".join(star(x, ey, 5, "spin", c["accent"], 2.2) for x in (cx - 14, cx + 14)),
        "idle": f'<g class="look"><g class="blink">'
                + "".join(f'<circle cx="{x}" cy="{ey}" r="3.4" fill="{c["text"]}"/>' for x in (cx - 14, cx + 14))
                + "</g></g>",
        "sleepy": "".join(f'<path d="M{x - 5} {ey}H{x + 5}" {ink}/>' for x in (cx - 14, cx + 14)),
        "hibernating": "".join(f'<path d="M{x - 5} {ey - 2}Q{x} {ey + 5} {x + 5} {ey - 2}" {ink}/>' for x in (cx - 14, cx + 14)),
    }[mood]
    mouth = {
        "happy": f'<path d="M{cx - 8} {my}Q{cx} {my + 7} {cx + 8} {my}" {ink}/>',
        "overclocked": f'<path d="M{cx - 8} {my - 1}H{cx + 8}Q{cx} {my + 11} {cx - 8} {my - 1}Z" fill="{c["accent"]}"/>',
        "idle": f'<path d="M{cx - 6} {my + 2}H{cx + 6}" {ink}/>',
        "sleepy": f'<path d="M{cx - 4} {my + 2}H{cx + 4}" {ink}/>',
        "hibernating": f'<path d="M{cx - 8} {my + 2}q2 -3 4 0t4 0t4 0t4 0" {ink}/>',
    }[mood]
    cheeks = "".join(
        f'<circle cx="{x}" cy="{hy + 30}" r="3.2" fill="{c["accent"]}" opacity=".45"/>' for x in (cx - 24, cx + 24)
    ) if mood in ("happy", "overclocked") else ""
    antenna_cls = {"overclocked": "pulse-fast", "hibernating": ""}.get(mood, "pulse")
    antenna_fill = c["dim"] if mood == "hibernating" else c["accent"]

    body = (
        f'<path d="M{cx} {hy}V{hy - 12}" {ink}/>'
        f'<circle class="{antenna_cls}" cx="{cx}" cy="{hy - 15}" r="4" fill="{antenna_fill}"/>'
        f'<rect x="{cx - 34}" y="{hy}" width="68" height="48" rx="12" fill="{c["bg"]}" stroke="{c["text"]}" stroke-width="2.2"/>'
        f"{eyes}{mouth}{cheeks}"
        f'<rect x="{cx - 20}" y="{hy + 52}" width="40" height="18" rx="5" fill="{c["bg"]}" stroke="{c["text"]}" stroke-width="2.2"/>'
        f'<circle class="{antenna_cls}" cx="{cx}" cy="{hy + 61}" r="2.6" fill="{antenna_fill}"/>'
        f'<path d="M{cx - 10} {hy + 70}V{hy + 80}M{cx + 10} {hy + 70}V{hy + 80}" {ink}/>'
    )
    motion = {
        "happy": ("bob", "hop"),
        "overclocked": ("bob-fast", "hop-fast"),
        "idle": ("bob", ""),
        "sleepy": ("", "breathe"),
        "hibernating": ("", "breathe-slow"),
    }[mood]
    zs = ""
    if mood in ("sleepy", "hibernating"):
        zs = "".join(
            f'<text class="z" style="animation-delay:-{i}s" x="{cx + 38 + i * 4}" y="{hy - 4}" '
            f'font-size="{13 + i * 2}" fill="{c["dim"]}">z</text>'
            for i in range(3 if mood == "hibernating" else 2)
        )
    stage = (
        f'<g class="{motion[0]}"><g class="{motion[1]}">{body}</g></g>{zs}'
        f'<text x="{cx}" y="{hy + 98}" text-anchor="middle" font-size="12" fill="{c["dim"]}">TJ-02</text>'
    )

    # Speech bubble, wrapped to fit the right column, with its text typed in.
    lines = textwrap.wrap(r["message"], 30)
    bw = max(len(line) for line in lines) * 7.8 + 24
    bh = len(lines) * 18 + 14
    bx = min(W - 16 - bw, cx + 24 - bw / 2)
    by = hy - 34 - bh
    tail = cx - 4
    rad = 8
    bubble_path = (
        f"M{num(bx + rad)} {num(by)}H{num(bx + bw - rad)}A{rad} {rad} 0 0 1 {num(bx + bw)} {num(by + rad)}"
        f"V{num(by + bh - rad)}A{rad} {rad} 0 0 1 {num(bx + bw - rad)} {num(by + bh)}"
        f"H{num(tail + 7)}L{num(tail - 3)} {num(by + bh + 11)}L{num(tail - 5)} {num(by + bh)}"
        f"H{num(bx + rad)}A{rad} {rad} 0 0 1 {num(bx)} {num(by + bh - rad)}V{num(by + rad)}"
        f"A{rad} {rad} 0 0 1 {num(bx + rad)} {num(by)}Z"
    )
    t = BUBBLE_AT + 0.25
    texts = []
    for i, line in enumerate(lines):
        texts.append(s.typed(bx + 12, by + 22 + i * 18, line, 13, c["text"], t, 0.035))
        t += len(line) * 0.035 + 0.1
    bubble = (
        f'<g class="{s.pop(BUBBLE_AT, "left bottom")}"><path d="{bubble_path}" fill="{c["bg"]}" '
        f'stroke="{c["accent"]}" stroke-width="1.4"/>{"".join(texts)}</g>'
    )

    # Sub-agents: one per two days of streak, each popping in and bouncing.
    subs = []
    for i in range(r["subagents"]):
        x, ground = cx + 66 + i * 32, hy + 80
        mini = (
            f'<path d="M{x} {ground - 30}V{ground - 36}" stroke="{c["text"]}" stroke-width="1.6" stroke-linecap="round"/>'
            f'<circle cx="{x}" cy="{ground - 38}" r="2.2" fill="{c["accent"]}"/>'
            f'<rect x="{x - 12}" y="{ground - 30}" width="24" height="19" rx="6" fill="{c["bg"]}" stroke="{c["text"]}" stroke-width="1.6"/>'
            f'<circle cx="{x - 5}" cy="{ground - 21}" r="1.9" fill="{c["text"]}"/>'
            f'<circle cx="{x + 5}" cy="{ground - 21}" r="1.9" fill="{c["text"]}"/>'
            f'<path d="M{x - 5} {ground - 11}V{ground - 5}M{x + 5} {ground - 11}V{ground - 5}" stroke="{c["text"]}" stroke-width="1.6" stroke-linecap="round"/>'
        )
        subs.append(
            f'<g class="{s.pop(SUBAGENT_AT + i * 0.3, "center bottom")}">'
            f'<g class="bounce" style="animation-delay:-{i * 0.3:.1f}s">{mini}</g></g>'
        )
    return stage, bubble + "".join(subs)


def build(theme_name: str, r: dict) -> str:
    c = THEMES[theme_name]
    s = Scene(c)
    lines = transcript(s, r)
    stage, extras = tj02(s, r)
    fade = (
        f"@keyframes replay{{0%,{at(FADE[0])}{{opacity:1}}{at(FADE[1])},100%{{opacity:0}}}}"
        f".replay{{animation:replay {CYCLE}s infinite}}"
    )
    css = "\n    ".join(s.css)
    desc = (
        f"An animated Claude Code-style session. /activity reports {r['summary']}; "
        f"{round(r['used'] * 100)}% of {r['today'].year} used, auto-compacting on Jan 1; "
        f"today's omikuji: {r['rank']}, {r['fortune']}. TJ-02 the agent is {r['mood']} and says: {r['message']}"
    )
    header_star = star(X0 + 6, 25, 5, "", c["accent"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
  <title id="title">TJ-02's activity report</title>
  <desc id="desc">{escape(desc)}</desc>
  <!-- Generated by scripts/update_activity.py ({theme_name} theme). -->
  <defs>
    <linearGradient id="shimmer-fill" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="90" y2="0">
      <stop offset="0" stop-color="{c["accent"]}"/>
      <stop offset=".5" stop-color="{c["glow"]}"/>
      <stop offset="1" stop-color="{c["accent"]}"/>
      <animateTransform attributeName="gradientTransform" type="translate" values="-120 0;260 0" dur="1.8s" repeatCount="indefinite"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-family: {MONO}; font-size: {FONT}px; }}
    .shimmer {{ fill: url(#shimmer-fill); }}
    .twinkle, .spin {{ transform-box: fill-box; transform-origin: center; }}
    .twinkle {{ animation: twinkle 1.2s ease-in-out infinite; }}
    .spin {{ animation: spin 1.6s linear infinite; }}
    .pulse {{ animation: pulse 1.6s ease-in-out infinite; }}
    .pulse-fast {{ animation: pulse .5s ease-in-out infinite; }}
    .bob {{ animation: bob 2.4s ease-in-out infinite; }}
    .bob-fast {{ animation: bob 1.1s ease-in-out infinite; }}
    .hop {{ animation: hop 3.2s ease-out infinite; }}
    .hop-fast {{ animation: hop 1.6s ease-out infinite; }}
    .look {{ animation: look 7s ease-in-out infinite; }}
    .blink {{ transform-box: fill-box; transform-origin: center; animation: blink 4.2s infinite; }}
    .breathe, .breathe-slow {{ transform-box: fill-box; transform-origin: center bottom; }}
    .breathe {{ animation: breathe 3.6s ease-in-out infinite; }}
    .breathe-slow {{ animation: breathe 5.5s ease-in-out infinite; }}
    .bounce {{ animation: bounce .9s ease-in-out infinite; }}
    .z {{ opacity: 0; animation: zfloat 3s ease-out infinite; }}
    @keyframes twinkle {{ 0%, 100% {{ transform: rotate(0) scale(1); }} 50% {{ transform: rotate(90deg) scale(.7); }} }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .25; }} }}
    @keyframes bob {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-3px); }} }}
    @keyframes hop {{ 0%, 70%, 100% {{ transform: translateY(0); }} 78% {{ transform: translateY(-10px); }} 86% {{ transform: translateY(0); }} 91% {{ transform: translateY(-3px); }} 96% {{ transform: translateY(0); }} }}
    @keyframes look {{ 0%, 20%, 100% {{ transform: translateX(0); }} 30%, 45% {{ transform: translateX(-3px); }} 60%, 75% {{ transform: translateX(3px); }} }}
    @keyframes blink {{ 0%, 90%, 100% {{ transform: scaleY(1); }} 94% {{ transform: scaleY(.1); }} }}
    @keyframes breathe {{ 0%, 100% {{ transform: scale(1, 1); }} 50% {{ transform: scale(1.02, 1.05); }} }}
    @keyframes bounce {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-5px); }} }}
    @keyframes zfloat {{ 0% {{ opacity: 0; transform: translate(0, 0); }} 20% {{ opacity: 1; }} 100% {{ opacity: 0; transform: translate(10px, -26px); }} }}
    {fade}
    {css}
    @media (prefers-reduced-motion: reduce) {{
      * {{ animation: none !important; }}
      .shimmer {{ fill: {c["accent"]}; }}
      .z {{ opacity: 1; }}
    }}
  </style>
  <rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="10" fill="{c["bg"]}" stroke="{c["border"]}"/>
  {header_star}
  <text x="{X0 + 18}" y="30" font-size="13"><tspan fill="{c["accent"]}" font-weight="700">TJ-02</tspan><tspan fill="{c["dim"]}"> · daily activity report</tspan></text>
  <text x="{W - X0}" y="30" font-size="12" text-anchor="end" fill="{c["dim"]}">updated {r["today"].isoformat()}</text>
  <path d="M1 42H{W - 1}" stroke="{c["border"]}"/>
  {stage}
  <g class="replay">
  {lines}
  {extras}
  </g>
</svg>
"""


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


def build_overview(theme_name: str, o: dict) -> str:
    c = THEMES[theme_name]
    cx, cy, R = RADAR_X, RADAR_Y, RADAR_R
    pcts = o["pcts"]
    peak = max(pcts.values()) or 1  # like GitHub, the largest share reaches the axis end

    points = [
        (label, cx + dx * R * pcts[label] / peak, cy + dy * R * pcts[label] / peak)
        for label, _, (dx, dy) in AXES
    ]
    polygon = "M" + "L".join(f"{num(x)} {num(y)}" for _, x, y in points) + "Z"

    # Radar sweep: a 50° wedge, transparent at its trailing edge, rotating around the centre.
    rw = R + 10
    bx, by = cx + rw * 0.766, cy - rw * 0.6428
    sweep = (
        f'<g class="sweep"><path d="M{cx} {cy}L{cx} {cy - rw}A{rw} {rw} 0 0 1 {num(bx)} {num(by)}Z" fill="url(#sweep)"/>'
        f'<path d="M{cx} {cy}L{num(bx)} {num(by)}" stroke="{c["accent"]}" stroke-opacity=".55" stroke-width="1.2"/></g>'
    )
    rings = "".join(
        f'<circle cx="{cx}" cy="{cy}" r="{num(R * f)}" fill="none" stroke="{c["border"]}" stroke-dasharray="2 4"/>'
        for f in (0.5, 1.0)
    )
    axes = (
        f'<path d="M{cx} {cy - R - 10}V{cy + R + 10}M{cx - R - 10} {cy}H{cx + R + 10}" '
        f'stroke="{c["accent"]}" stroke-width="2" stroke-linecap="round"/>'
    )
    markers = []
    for i, (label, x, y) in enumerate(points):
        if not pcts[label]:
            continue
        markers.append(
            f'<circle class="ping" style="animation-delay:{1.4 + i * 0.6:.1f}s" cx="{num(x)}" cy="{num(y)}" r="5" '
            f'fill="none" stroke="{c["accent"]}" stroke-width="1.5"/>'
            f'<circle class="pop" style="animation-delay:{1.2 + i * 0.15:.2f}s" cx="{num(x)}" cy="{num(y)}" r="5" '
            f'fill="{c["bg"]}" stroke="{c["accent"]}" stroke-width="2.4"/>'
        )

    def axis_label(label: str, x: float, y: float, anchor: str) -> str:
        pct = pcts[label]
        lines = ([(f"{pct}%", c["text"], "700")] if pct else []) + [(label, c["dim"], "400")]
        return "".join(
            f'<text x="{num(x)}" y="{num(y + i * 16)}" text-anchor="{anchor}" font-size="13" '
            f'fill="{color}" font-weight="{weight}">{escape(text)}</text>'
            for i, (text, color, weight) in enumerate(lines)
        )

    def side(label: str) -> float:  # vertical start so one or two lines sit centred on the axis
        return cy - 4 if pcts[label] else cy + 4

    labels = (
        axis_label("Code review", cx, cy - R - 20 - (16 if pcts["Code review"] else 0), "middle")
        + axis_label("Issues", cx + R + 20, side("Issues"), "start")
        + axis_label("Pull requests", cx, cy + R + 28, "middle")
        + axis_label("Commits", cx - R - 20, side("Commits"), "end")
    )

    # Left panel: where the contributions went, as bars that grow in.
    rows = sorted(AXES, key=lambda a: -o["counts"][a[0]])
    bars = []
    for i, (label, _, _) in enumerate(rows):
        y = 150 + i * 32
        pct = pcts[label]
        bars.append(
            f'<text x="24" y="{y}" font-size="13" fill="{c["text"]}">{escape(label)}</text>'
            f'<text x="182" y="{y}" font-size="13" text-anchor="end" fill="{c["dim"]}">{o["counts"][label]:,}</text>'
            f'<rect x="196" y="{y - 9}" width="150" height="9" rx="4.5" fill="{c["track"]}"/>'
            + (f'<rect class="bar" style="animation-delay:{0.4 + i * 0.12:.2f}s" x="196" y="{y - 9}" '
               f'width="{num(150 * pct / 100)}" height="9" rx="4.5" fill="{c["accent"]}"/>' if pct else "")
            + f'<text x="358" y="{y}" font-size="13" fill="{c["text"]}" font-weight="700">{pct}%</text>'
        )
    repo_icon = (
        f'<path d="M26 72.5h9.5v13H28a2 2 0 0 1-2-2zM26 83.5a2 2 0 0 1 2-2h7.5" fill="none" '
        f'stroke="{c["dim"]}" stroke-width="1.4" stroke-linejoin="round"/>'
    )
    private = (
        f'<text x="44" y="104" font-size="12" fill="{c["dim"]}">plus {plural(o["private"], "private contribution")}</text>'
        if o["private"] else ""
    )
    repos_text = f"{o['repos']:,} {'repository' if o['repos'] == 1 else 'repositories'}"
    summary = "; ".join(f"{label} {pcts[label]}%" for label, _, _ in AXES)
    desc = f"Activity overview for the past year: {summary}. Contributed to {repos_text}."
    header_star = star(X0 + 6, 25, 5, "", c["accent"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{OVERVIEW_H}" viewBox="0 0 {W} {OVERVIEW_H}" role="img" aria-labelledby="title desc">
  <title id="title">Activity overview</title>
  <desc id="desc">{escape(desc)}</desc>
  <!-- Generated by scripts/update_activity.py ({theme_name} theme). -->
  <defs>
    <linearGradient id="sweep" gradientUnits="userSpaceOnUse" x1="{cx}" y1="{cy - rw}" x2="{num(bx)}" y2="{num(by)}">
      <stop offset="0" stop-color="{c["accent"]}" stop-opacity="0"/>
      <stop offset="1" stop-color="{c["accent"]}" stop-opacity=".32"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-family: {MONO}; font-size: {FONT}px; }}
    .grow {{ transform-origin: {cx}px {cy}px; animation: grow 1.2s cubic-bezier(.2, .9, .3, 1.25) .3s both; }}
    .sweep {{ transform-origin: {cx}px {cy}px; animation: sweep 4s linear infinite; }}
    .pop, .ping, .bar {{ transform-box: fill-box; }}
    .pop {{ transform-origin: center; animation: grow .5s cubic-bezier(.2, .9, .3, 1.6) both; }}
    .ping {{ transform-origin: center; opacity: 0; animation: ping 2.4s ease-out infinite; }}
    .bar {{ transform-origin: left; animation: bar 1s cubic-bezier(.2, .8, .2, 1) both; }}
    @keyframes grow {{ from {{ transform: scale(0); }} to {{ transform: scale(1); }} }}
    @keyframes sweep {{ to {{ transform: rotate(360deg); }} }}
    @keyframes ping {{ 0% {{ transform: scale(1); opacity: .8; }} 100% {{ transform: scale(3.2); opacity: 0; }} }}
    @keyframes bar {{ from {{ transform: scaleX(0); }} }}
    @media (prefers-reduced-motion: reduce) {{
      * {{ animation: none !important; }}
      .sweep {{ display: none; }}
    }}
  </style>
  <rect x=".5" y=".5" width="{W - 1}" height="{OVERVIEW_H - 1}" rx="10" fill="{c["bg"]}" stroke="{c["border"]}"/>
  {header_star}
  <text x="{X0 + 18}" y="30" font-size="13"><tspan fill="{c["accent"]}" font-weight="700">Activity overview</tspan></text>
  <text x="{W - X0}" y="30" font-size="12" text-anchor="end" fill="{c["dim"]}">past year</text>
  <path d="M1 42H{W - 1}" stroke="{c["border"]}"/>
  {repo_icon}
  <text x="44" y="84" font-size="14" fill="{c["text"]}">Contributed to <tspan font-weight="700">{repos_text}</tspan></text>
  {private}
  {"".join(bars)}
  <path d="M420 60V{OVERVIEW_H - 18}" stroke="{c["border"]}"/>
  {rings}
  {sweep}
  {axes}
  <path class="grow" d="{polygon}" fill="{c["accent"]}" fill-opacity=".28" stroke="{c["accent"]}" stroke-width="1.5" stroke-linejoin="round"/>
  {"".join(markers)}
  {labels}
</svg>
"""


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    out.mkdir(parents=True, exist_ok=True)
    coll = fetch(token)
    r, o = report(coll["contributionCalendar"]), overview(coll)
    for name in THEMES:
        for stem, svg in (("activity", build(name, r)), ("overview", build_overview(name, o))):
            path = out / f"{stem}-{name}.svg"
            path.write_text(svg, encoding="utf-8")
            print(f"wrote {path} ({path.stat().st_size:,} bytes)")
    print(f"mood={r['mood']} · overview={o['pcts']}")


if __name__ == "__main__":
    main()
