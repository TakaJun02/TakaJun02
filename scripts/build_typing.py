#!/usr/bin/env python3
"""Generate the typing-prompt SVGs shown under the name banner in README.md.

    python3 scripts/build_typing.py

Writes assets/typing-dark.svg and assets/typing-light.svg (standard library only).
Edit PHRASES or the timing constants below and re-run to update the animation.

How it works
- Each phrase sits under a clipPath whose width steps one character cell at a
  time (SMIL, calcMode="discrete"), so it types in, holds, and deletes itself.
  textLength pins every glyph to the same cell width, so the steps line up
  with whichever monospace font the viewer happens to have.
- A block cursor follows the text and blinks while the line is idle.
- prefers-reduced-motion hides the animated layer and shows a static line.
"""

from __future__ import annotations

import random
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"

PHRASES = [
    "Building AI Agents with LLMs",
    "Engineering RAG Systems",
    "Turning AI into Practical Solutions",
]

# Warm, Claude Code-like palettes. The background stays transparent so the
# line sits directly on GitHub's page colour in either theme.
THEMES = {
    "dark": {"accent": "#D97757", "text": "#E8E6DE"},
    "light": {"accent": "#C8643F", "text": "#1F1E1D"},
}

MONO = (
    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, '
    '"Liberation Mono", "DejaVu Sans Mono", monospace'
)

# Canvas and layout (viewBox units). The longest phrase is centred.
W, H = 640, 44
FONT = 20.0
CELL = FONT * 0.6                   # monospace advance
LONGEST = max(len(p) for p in PHRASES)
PROMPT_X = (W - (2 + LONGEST + 1) * CELL) / 2
TEXT_X = PROMPT_X + 2 * CELL
BASELINE = 29.0

# Timing (seconds).
PAUSE_BEFORE = 0.6
HOLD = 1.9
TYPE_MIN, TYPE_MAX = 0.055, 0.105
TYPE_AFTER_SPACE = 0.04
DELETE = 0.028
BLINK = 0.53


def num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def timeline() -> tuple[list[tuple[float, int, int, bool]], float]:
    """Frames of (time, phrase index, visible chars, cursor visible)."""
    rng = random.Random(2)  # fixed seed: the same "human" rhythm on every build
    frames: list[tuple[float, int, int, bool]] = []
    t = 0.0

    def idle(duration: float, i: int, n: int) -> None:
        nonlocal t
        end, on = t + duration, True
        while t < end - 1e-9:
            frames.append((t, i, n, on))
            t = min(t + BLINK, end)
            on = not on

    for i, phrase in enumerate(PHRASES):
        idle(PAUSE_BEFORE, i, 0)
        for k in range(1, len(phrase) + 1):
            frames.append((t, i, k, True))
            t += rng.uniform(TYPE_MIN, TYPE_MAX)
            if phrase[k - 1] == " ":
                t += TYPE_AFTER_SPACE
        idle(HOLD, i, len(phrase))
        for k in range(len(phrase) - 1, -1, -1):
            frames.append((t, i, k, True))
            t += DELETE
    return frames, t


def discrete(attr: str, samples: list[tuple[float, str]], dur: float) -> str:
    """A discrete SMIL <animate>, dropping samples that repeat the previous value."""
    kept: list[tuple[float, str]] = []
    for t, v in samples:
        if not kept or kept[-1][1] != v:
            kept.append((t, v))
    kept.append((dur, kept[-1][1]))
    values = ";".join(v for _, v in kept)
    key_times = ";".join(f"{t / dur:.4f}" for t, _ in kept)
    return (
        f'<animate attributeName="{attr}" values="{values}" keyTimes="{key_times}" '
        f'calcMode="discrete" dur="{dur:.3f}s" repeatCount="indefinite"/>'
    )


def build(name: str, theme: dict) -> str:
    frames, dur = timeline()
    cursor_y = BASELINE - FONT * 0.8
    cursor_h = FONT * 1.05

    def text(phrase: str) -> str:
        return (
            f'<text x="{num(TEXT_X)}" y="{num(BASELINE)}" textLength="{num(len(phrase) * CELL)}" '
            f'lengthAdjust="spacing">{escape(phrase)}</text>'
        )

    clips, layers = [], []
    for i, phrase in enumerate(PHRASES):
        widths = [(t, num(n * CELL if p == i else 0)) for t, p, n, _ in frames]
        clips.append(
            f'<clipPath id="type-{i}"><rect x="{num(TEXT_X)}" y="0" width="0" height="{H}">'
            f'{discrete("width", widths, dur)}</rect></clipPath>'
        )
        layers.append(f'<g clip-path="url(#type-{i})">{text(phrase)}</g>')

    cursor_x = [(t, num(TEXT_X + n * CELL)) for t, _, n, _ in frames]
    cursor_on = [(t, "1" if on else "0") for t, _, _, on in frames]
    cursor = (
        f'<rect x="{num(TEXT_X)}" y="{num(cursor_y)}" width="{num(CELL - 1.5)}" height="{num(cursor_h)}">'
        f'{discrete("x", cursor_x, dur)}{discrete("opacity", cursor_on, dur)}</rect>'
    )
    still = PHRASES[0]
    static = (
        f'<g class="static">{text(still)}'
        f'<rect x="{num(TEXT_X + len(still) * CELL)}" y="{num(cursor_y)}" '
        f'width="{num(CELL - 1.5)}" height="{num(cursor_h)}"/></g>'
    )
    desc = "A terminal prompt types, then deletes: " + "; ".join(PHRASES) + "."
    nl = "\n    "
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
  <title id="title">What I build</title>
  <desc id="desc">{escape(desc)}</desc>
  <!-- Generated by scripts/build_typing.py ({name} theme). Edit the script, not this file. -->
  <defs>
    {nl.join(clips)}
  </defs>
  <style>
    text {{ font-family: {MONO}; }}
    .static {{ display: none; }}
    @media (prefers-reduced-motion: reduce) {{
      .motion {{ display: none; }}
      .static {{ display: inline; }}
    }}
  </style>
  <text x="{num(PROMPT_X)}" y="{num(BASELINE)}" font-size="{num(FONT)}" fill="{theme["accent"]}">&gt;</text>
  <g font-size="{num(FONT)}" fill="{theme["text"]}">
    <g class="motion">
    {nl.join(layers)}
    {cursor}
    </g>
    {static}
  </g>
</svg>
"""


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        path = OUT_DIR / f"typing-{name}.svg"
        path.write_text(build(name, theme), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
