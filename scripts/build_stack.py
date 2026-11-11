#!/usr/bin/env python3
"""Generate the Tech stack badges, one per tool, each in its own brand's colours.

    python3 scripts/build_stack.py

Writes assets/stack/<name>.svg. Needs numpy, through build_hero.py.

A badge is the hero's block button at badge size: a flat block with a hard
offset shadow, the tool's logo, and its name in Silkscreen. What changes from
one to the next is the brand: the block takes the brand's colour, the logo its
real colours where it has more than one (Vue's green on slate, vLLM's yellow
and blue, Chroma's three circles, AWS's orange smile), and the shadow is the
block's colour, darkened. Claude Code's logo is Clawd and Codex's is the Codex
mark, both as the hero draws them.

Logos are Simple Icons' paths (CC0), kept in scripts/data/logos.json so a
build needs no network. To add one, copy the `d` of
https://cdn.jsdelivr.net/npm/simple-icons/icons/<slug>.svg into that file.
Chroma's mark is from its own repository. The logos are their owners'
trademarks.
"""

from __future__ import annotations

import json
from pathlib import Path

from terminal import CLAWD_H, CLAWD_W, CODEX, clawd_flat, codex_flat, fmt
from build_hero import BTN_BG, BTN_BORDER, BTN_CREAM, CLAY, OUT_DIR, pixel_path, text_width

LOGOS = json.loads((Path(__file__).resolve().parent / "data" / "logos.json").read_text())
STACK_DIR = OUT_DIR / "stack"

H, SHADOW = 30, 3              # the block, and how far its shadow is offset
PX = 2                         # px a pixel of the name: capitals 10 px tall
LOGO = 16                      # px the logo's 24-unit box is drawn at
PAD_L, GAP, PAD_R = 9, 8, 11

WHITE, BLACK = "#FFFFFF", "#000000"


def simple(slug, fill):
    return f'<path fill="{fill}" d="{LOGOS[slug]}"/>'


def vllm_logo():
    right, left = LOGOS["vllm"].split("M", 1)
    return f'<path fill="#0A2540" d="{right}"/><path fill="#FDB515" d="M{left}"/>'


def aws_logo():
    # The letters in white, the smile under them in AWS's orange.
    d = LOGOS["amazonwebservices"]
    return (f'<clipPath id="s"><rect y="13.6" width="24" height="10.4"/></clipPath>'
            f'<path fill="{WHITE}" d="{d}"/><path fill="#FF9900" clip-path="url(#s)" d="{d}"/>')


CHROMA = ('<circle cx="15.92" cy="12" r="7.6" fill="#FFDE2D"/><circle cx="8.08" cy="12" r="7.6" fill="#327EFF"/>'
          '<path fill="#FF6446" d="M15.92 12A7.7 7.6 0 0 1 8.08 19.52V12ZM8.08 12A7.7 7.6 0 0 1 15.92 4.48V12Z"/>')

# A magnifying glass on an 8 x 8 pixel grid: retrieval. RAG has no logo of its own.
SEARCH = (".####.../#....#../#....#../#....#../#....#../.####.../.....##./......##")


def pixels(bitmap, fill, size=24):
    rows = bitmap.split("/")
    u = size / len(rows)
    d = "".join(f"M{fmt(c * u)} {fmt(r * u)}h{fmt(u)}v{fmt(u)}h{fmt(-u)}z"
                for r, row in enumerate(rows) for c, ch in enumerate(row) if ch == "#")
    return f'<path fill="{fill}" shape-rendering="crispEdges" d="{d}"/>'


def clawd_logo():
    u = 24 / CLAWD_W
    return clawd_flat(0, (24 - CLAWD_H * u) / 2, u, CLAY)


# (file, name, block, ink, logo in a 24-unit box, border)
BADGES = [
    ("langgraph", "LangGraph", "#1C3C3C", WHITE, simple("langgraph", WHITE), None),
    ("langchain", "LangChain", "#1C3C3C", WHITE, simple("langchain", WHITE), None),
    ("claude-api", "Claude API", CLAY, BTN_BG, simple("claude", BTN_BG), None),
    ("openai-api", "OpenAI API", BLACK, WHITE, simple("openai", WHITE), BTN_BORDER),
    ("ollama", "Ollama", WHITE, BLACK, simple("ollama", BLACK), BLACK),
    ("vllm", "vLLM", "#30A2FF", "#0A2540", vllm_logo(), None),
    ("rag", "RAG", "#262624", BTN_CREAM, pixels(SEARCH, CLAY), BTN_BORDER),
    ("python", "Python", "#3776AB", WHITE, simple("python", "#FFD43B"), None),
    ("typescript", "TypeScript", "#3178C6", WHITE, simple("typescript", WHITE), None),
    ("javascript", "JavaScript", "#F7DF1E", BLACK, simple("javascript", BLACK), None),
    ("fastapi", "FastAPI", "#009688", WHITE, simple("fastapi", WHITE), None),
    ("vue", "Vue.js", "#35495E", WHITE, simple("vuedotjs", "#41B883"), None),
    ("postgresql", "PostgreSQL", "#336791", WHITE, simple("postgresql", WHITE), None),
    ("sqlite", "SQLite", "#003B57", WHITE, simple("sqlite", "#7CC4F0"), None),
    ("chromadb", "ChromaDB", "#FAFAF9", BLACK, CHROMA, BLACK),
    ("qdrant", "Qdrant", "#DC244C", WHITE, simple("qdrant", WHITE), None),
    ("docker", "Docker", "#1D63ED", WHITE, simple("docker", WHITE), None),
    ("aws", "AWS", "#232F3E", WHITE, aws_logo(), None),
    ("git", "Git", "#F05032", WHITE, simple("git", WHITE), None),
    ("github", "GitHub", "#181717", WHITE, simple("github", WHITE), BTN_BORDER),
    ("linux", "Linux", "#FCC624", BLACK, simple("linux", BLACK), None),
    ("claude-code", "Claude Code", BTN_CREAM, BTN_BG, clawd_logo(), None),
    ("codex", "Codex", "#0F0F11", WHITE, codex_flat(12, 12, 24 / 17.2, CODEX), BTN_BORDER),
]


def darker(colour, keep=0.5):
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(round(c * keep) for c in (r, g, b)))


def badge(name, block, ink, logo, border):
    label = name.upper()
    text_x = PAD_L + LOGO + GAP
    w = round(text_x + text_width(label, PX) + PAD_R)
    edge = (f'<rect x="1" y="1" width="{w - 2}" height="{H - 2}" fill="none" stroke="{border}" stroke-width="2"/>'
            if border else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w + SHADOW} {H + SHADOW}" width="{w + SHADOW}" '
            f'height="{H + SHADOW}" role="img" aria-label="{name}"><title>{name}</title>'
            f'<rect x="{SHADOW}" y="{SHADOW}" width="{w}" height="{H}" fill="{darker(block)}"/>'
            f'<rect width="{w}" height="{H}" fill="{block}"/>{edge}'
            f'<g transform="translate({PAD_L} {(H - LOGO) / 2:g}) scale({fmt(LOGO / 24)})">{logo}</g>'
            f'<path fill="{ink}" shape-rendering="crispEdges" d="{pixel_path(label, text_x, (H - 5 * PX) // 2, PX)}"/></svg>')


def main():
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    for file, name, block, ink, logo, border in BADGES:
        (STACK_DIR / f"{file}.svg").write_text(badge(name, block, ink, logo, border), encoding="utf-8")
    print(f"{len(BADGES)} badges in {STACK_DIR.relative_to(OUT_DIR.parent)}")


if __name__ == "__main__":
    main()
