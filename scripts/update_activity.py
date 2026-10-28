#!/usr/bin/env python3
"""Refresh the Activity block in README.md from the GitHub GraphQL API.

    GITHUB_TOKEN=... python3 scripts/update_activity.py

Run daily by .github/workflows/activity.yml (standard library only). Rewrites
only the lines between the activity markers, as a Claude Code-style transcript:
contribution totals, streaks, weekly rhythm, and the language mix of public
repositories. No repository names are listed, only aggregate numbers.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LOGIN = os.environ.get("GITHUB_REPOSITORY_OWNER", "TakaJun02")
START, END = "<!-- activity:start -->", "<!-- activity:end -->"

# Spinner verbs in the spirit of Claude Code's, with an agent/RAG twist.
# One is picked per day, so the last line changes as the README refreshes.
VERBS = [
    "Retrieving", "Reranking", "Embedding", "Chunking", "Orchestrating",
    "Delegating", "Grounding", "Reflecting", "Planning", "Tool-calling",
    "Pondering", "Distilling",
]
WEEKDAYS = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date weekday contributionCount } }
      }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      nodes {
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
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
    return body["data"]["user"]


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


def transcript(user: dict) -> str:
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days]
    total = calendar["totalContributions"]
    active = sum(1 for c in counts if c)
    current, longest = streaks(counts)

    by_weekday = Counter()
    for d in days:
        by_weekday[d["weekday"]] += d["contributionCount"]
    best = max(days, key=lambda d: (d["contributionCount"], d["date"]))
    best_day = date.fromisoformat(best["date"])

    sizes = Counter()
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            sizes[edge["node"]["name"]] += edge["size"]
    lang_total = sum(sizes.values())
    langs = " · ".join(
        f"{name} {round(size * 100 / lang_total)}%" for name, size in sizes.most_common(4)
    ) if lang_total else "nothing public yet"

    if total:
        rhythm = (
            f"busiest on {WEEKDAYS[by_weekday.most_common(1)[0][0]]} · "
            f"best day {best_day:%b} {best_day.day} with {best['contributionCount']:,}"
        )
    else:
        rhythm = "warming up"
    verb = VERBS[date.fromisoformat(days[-1]["date"]).toordinal() % len(VERBS)]

    return "\n".join([
        "```text",
        "> /activity",
        "",
        "● Contributions(past year)",
        f"  ⎿  {plural(total, 'contribution')} on {plural(active, 'active day')}",
        "● Streak()",
        f"  ⎿  current {plural(current, 'day')} · longest {plural(longest, 'day')}",
        "● Rhythm()",
        f"  ⎿  {rhythm}",
        "● Languages(public repos)",
        f"  ⎿  {langs}",
        "",
        f"✻ {verb}… (esc to interrupt)",
        "```",
    ])


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    block = transcript(fetch(token))
    readme = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(readme):
        raise SystemExit(f"markers {START} / {END} not found in README.md")
    README.write_text(pattern.sub(f"{START}\n{block}\n{END}", readme), encoding="utf-8")
    print(block)


if __name__ == "__main__":
    main()
