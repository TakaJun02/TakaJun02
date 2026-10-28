#!/usr/bin/env python3
"""Refresh the Activity block in README.md from the GitHub GraphQL API.

    GITHUB_TOKEN=... python3 scripts/update_activity.py

Run daily by .github/workflows/activity.yml (standard library only). Rewrites
only the lines between the activity markers with a Claude Code-style session:

- TJ-02, a small agent whose mood follows the contribution calendar. A streak
  spawns sub-agents; days without commits send it to sleep.
- The year as a context window that auto-compacts on Jan 1.
- A daily omikuji (fortune slip) for agent builders.

Only aggregate numbers are used; no repository names are listed.
"""

from __future__ import annotations

import json
import os
import random
import re
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LOGIN = os.environ.get("GITHUB_REPOSITORY_OWNER", "TakaJun02")
START, END = "<!-- activity:start -->", "<!-- activity:end -->"

# Spinner verbs in the spirit of Claude Code's, with an agent/RAG twist.
VERBS = [
    "Retrieving", "Reranking", "Embedding", "Chunking", "Orchestrating",
    "Delegating", "Grounding", "Reflecting", "Planning", "Tool-calling",
    "Pondering", "Distilling",
]

# TJ-02's moods: (eyes, mouth, floating above its head).
FACES = {
    "overclocked": ("*", "\\_/", ""),
    "happy": ("^", "\\_/", ""),
    "idle": ("o", "___", ""),
    "sleepy": ("-", "___", "z Z"),
    "hibernating": ("u", "~~~", "z Z Z"),
}
LINES = {
    "overclocked": ["{streak}-day streak! Spawned {subs}.", "{streak} days in a row. My context is on fire."],
    "happy": ["Shipped today. Streak: {streak_days}.", "{today} today. Into the vector store it goes.", "Fresh commits today. Nom nom."],
    "idle": ["No commits since {last}. Feed me a diff?", "Idle since {last}. Polling for pushes..."],
    "sleepy": ["zZ... wake me up when a PR lands.", "{idle} days quiet. Entering low-power mode."],
    "hibernating": ["{idle} days without commits. Hibernating.", "Context compacted. Waiting for commits."],
}
OMIKUJI = [
    ("大吉", "tests pass on the first run"),
    ("大吉", "the retriever nails top-1"),
    ("中吉", "the agent stops exactly when it should"),
    ("中吉", "the reranker agrees with you"),
    ("中吉", "a sub-agent finds the missing doc"),
    ("小吉", "one flaky test, then all green"),
    ("小吉", "the prompt works after one small tweak"),
    ("吉", "everything fits in the context window, barely"),
    ("吉", "the embeddings cluster the way you hoped"),
    ("末吉", "merge conflicts, but small ones"),
    ("末吉", "the LLM is confident and mostly right"),
    ("凶", "rate limited until tomorrow"),
    ("凶", "the agent loops; add a stop condition"),
]

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
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
    return body["data"]["user"]["contributionsCollection"]["contributionCalendar"]


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


def tj02(mood: str, message: str, subagents: int) -> list[str]:
    """TJ-02 with a speech bubble; sub-agents line up next to its feet."""
    eyes, mouth, above = FACES[mood]
    rule = "─" * (len(message) + 2)
    feet = "   └──┬───┬──┘"
    if subagents:
        feet += "   " + " ".join(["[^_^]"] * subagents)
    return ([" " * 9 + above] if above else []) + [
        f"   ┌─────────┐   ╭{rule}╮",
        f"   │  {eyes}   {eyes}  │ ──┤ {message} │",
        f"   │   {mouth}   │   ╰{rule}╯",
        feet,
        "      TJ-02",
    ]


def session(calendar: dict) -> str:
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
    filled = round(used * 20)
    rank, fortune = rng.choice(OMIKUJI)

    return "\n".join([
        "```text",
        "> /activity",
        "",
        *tj02(mood, message, subagents),
        "",
        "● Contributions(past year)",
        f"  ⎿  {plural(calendar['totalContributions'], 'contribution')} · "
        f"{plural(len(active), 'active day')} · best streak {plural(longest, 'day')}",
        f"● Context({today.year})",
        f"  ⎿  {'█' * filled}{'░' * (20 - filled)} {round(used * 100)}% used · auto-compact on Jan 1",
        "● Omikuji(today)",
        f"  ⎿  {rank} — {fortune}",
        "",
        f"✻ {rng.choice(VERBS)}… (esc to interrupt)",
        "```",
    ])


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    block = session(fetch(token))
    readme = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(readme):
        raise SystemExit(f"markers {START} / {END} not found in README.md")
    README.write_text(pattern.sub(f"{START}\n{block}\n{END}", readme), encoding="utf-8")
    print(block)


if __name__ == "__main__":
    main()
