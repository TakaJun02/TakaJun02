#!/usr/bin/env python3
"""Generate the Tech stack tiles, one per tool, each in its own brand's colours.

    python3 scripts/build_stack.py

Writes assets/stack/<name>.svg. Needs numpy, through build_hero.py.

A tile is the hero's block button made square: a flat block with a hard offset
shadow and, on it, the tool's logo, large. The logo says what the tool is, so
there is no name on the tile; README.md gives each image its name as alt text
and as a title, which shows on hover. What changes from one tile to the next
is the brand: the block takes the brand's colour, the logo its real colours
where it has more than one (Vue's green on slate, vLLM's yellow and navy,
Chroma's three circles, AWS's orange smile), and the shadow is the block's
colour, darkened. Claude Code's logo is Clawd and Codex's is the Codex mark,
both as the hero draws them. RAG has no logo, so its tile is a pixel
magnifying glass over its three letters.

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

SIDE, SHADOW = 48, 4           # the block, and how far its shadow is offset
LOGO = 28                      # px the logo's 24-unit box is drawn at
PX = 2                         # px a pixel of RAG's letters

WHITE, BLACK = "#FFFFFF", "#000000"


CHROMA = ('<circle cx="15.92" cy="12" r="7.6" fill="#FFDE2D"/><circle cx="8.08" cy="12" r="7.6" fill="#327EFF"/>'
          '<path fill="#FF6446" d="M15.92 12A7.7 7.6 0 0 1 8.08 19.52V12ZM8.08 12A7.7 7.6 0 0 1 15.92 4.48V12Z"/>')

# A magnifying glass on an 8 x 8 pixel grid: retrieval. RAG has no logo of its own.
SEARCH = (".####.../#....#../#....#../#....#../#....#../.####.../.....##./......##")


def boxed(logo):
    """A logo drawn in a 24-unit box, centred on the tile."""
    return f'<g transform="translate({(SIDE - LOGO) / 2:g} {(SIDE - LOGO) / 2:g}) scale({fmt(LOGO / 24)})">{logo}</g>'


def simple(slug, fill):
    return boxed(f'<path fill="{fill}" d="{LOGOS[slug]}"/>')


def vllm_logo():
    right, left = LOGOS["vllm"].split("M", 1)
    return boxed(f'<path fill="#0A2540" d="{right}"/><path fill="#FDB515" d="M{left}"/>')


def aws_logo():
    # The letters in white, the smile under them in AWS's orange.
    d = LOGOS["amazonwebservices"]
    return boxed(f'<clipPath id="s"><rect y="13.6" width="24" height="10.4"/></clipPath>'
                 f'<path fill="{WHITE}" d="{d}"/><path fill="#FF9900" clip-path="url(#s)" d="{d}"/>')


def clawd_logo():
    u = 2                          # whole pixels: 34 x 20
    return clawd_flat((SIDE - CLAWD_W * u) / 2, (SIDE - CLAWD_H * u) / 2, u, CLAY)


def rag_logo():
    u, rows = 3, SEARCH.split("/")
    x0, y0 = (SIDE - 8 * u) // 2, 5
    glass = "".join(f"M{x0 + c * u} {y0 + r * u}h{u}v{u}h{-u}z"
                    for r, row in enumerate(rows) for c, ch in enumerate(row) if ch == "#")
    letters = pixel_path("RAG", round((SIDE - text_width("RAG", PX)) / 2), y0 + 8 * u + 4, PX)
    return (f'<g shape-rendering="crispEdges"><path fill="{CLAY}" d="{glass}"/>'
            f'<path fill="{BTN_CREAM}" d="{letters}"/></g>')


# (file, name, block, logo, border)
TILES = [
    ("langgraph", "LangGraph", "#1C3C3C", simple("langgraph", WHITE), None),
    ("langchain", "LangChain", "#1C3C3C", simple("langchain", WHITE), None),
    ("claude-api", "Claude API", CLAY, simple("claude", BTN_BG), None),
    ("openai-api", "OpenAI API", BLACK, simple("openai", WHITE), BTN_BORDER),
    ("ollama", "Ollama", WHITE, simple("ollama", BLACK), BLACK),
    ("vllm", "vLLM", "#30A2FF", vllm_logo(), None),
    ("rag", "RAG", "#262624", rag_logo(), BTN_BORDER),
    ("python", "Python", "#3776AB", simple("python", "#FFD43B"), None),
    ("typescript", "TypeScript", "#3178C6", simple("typescript", WHITE), None),
    ("javascript", "JavaScript", "#F7DF1E", simple("javascript", BLACK), None),
    ("fastapi", "FastAPI", "#009688", simple("fastapi", WHITE), None),
    ("vue", "Vue.js", "#35495E", simple("vuedotjs", "#41B883"), None),
    ("postgresql", "PostgreSQL", "#336791", simple("postgresql", WHITE), None),
    ("sqlite", "SQLite", "#003B57", simple("sqlite", "#7CC4F0"), None),
    ("chromadb", "ChromaDB", "#FAFAF9", boxed(CHROMA), BLACK),
    ("qdrant", "Qdrant", "#DC244C", simple("qdrant", WHITE), None),
    ("docker", "Docker", "#1D63ED", simple("docker", WHITE), None),
    ("aws", "AWS", "#232F3E", aws_logo(), None),
    ("git", "Git", "#F05032", simple("git", WHITE), None),
    ("github", "GitHub", "#181717", simple("github", WHITE), BTN_BORDER),
    ("linux", "Linux", "#FCC624", simple("linux", BLACK), None),
    ("claude-code", "Claude Code", BTN_CREAM, clawd_logo(), None),
    ("codex", "Codex", "#0F0F11", codex_flat(SIDE / 2, SIDE / 2, 30 / 17.2, CODEX), BTN_BORDER),
]


def darker(colour, keep=0.5):
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(round(c * keep) for c in (r, g, b)))


def tile(name, block, logo, border):
    edge = (f'<rect x="1" y="1" width="{SIDE - 2}" height="{SIDE - 2}" fill="none" stroke="{border}" stroke-width="2"/>'
            if border else "")
    full = SIDE + SHADOW
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {full} {full}" width="{full}" height="{full}" '
            f'role="img" aria-label="{name}"><title>{name}</title>'
            f'<rect x="{SHADOW}" y="{SHADOW}" width="{SIDE}" height="{SIDE}" fill="{darker(block)}"/>'
            f'<rect width="{SIDE}" height="{SIDE}" fill="{block}"/>{edge}{logo}</svg>')


def main():
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    for file, name, block, logo, border in TILES:
        (STACK_DIR / f"{file}.svg").write_text(tile(name, block, logo, border), encoding="utf-8")
    print(f"{len(TILES)} tiles in {STACK_DIR.relative_to(OUT_DIR.parent)}")


if __name__ == "__main__":
    main()
