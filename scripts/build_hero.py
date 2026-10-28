#!/usr/bin/env python3
"""Generate the animated hero SVGs used at the top of README.md.

    python3 scripts/build_hero.py

Writes assets/hero-dark.svg and assets/hero-light.svg (standard library only).
Edit PHRASES or the timing constants below and re-run to update the animation.

How it works
- The name banner is the figlet font "ANSI Shadow", drawn as SVG shapes rather
  than text so it renders the same everywhere: full blocks become rects and the
  box-drawing "shadow" characters become thin double strokes.
- The prompt line is a SMIL animation: each phrase sits under a clipPath whose
  width steps one character cell at a time (calcMode="discrete"). textLength
  pins every glyph to the same cell width, so the steps line up with any
  monospace font the viewer happens to have.
- prefers-reduced-motion hides the animated layer and shows a static line.
"""

from __future__ import annotations

import random
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"

HANDLE = "TakaJun02"
ROLE = ("AI Agent", "RAG Engineer")
STATUS_LEFT = "? for shortcuts"
STATUS_RIGHT = "github.com/TakaJun02  ·  takajun02.com"
PHRASES = [
    "Building AI Agents with LLMs",
    "Engineering RAG Systems",
    "Turning AI into Practical Solutions",
]

# "JUNTA TAKAHASHI" rendered with figlet's ANSI Shadow font.
BANNER = [
    "     ██╗██╗   ██╗███╗   ██╗████████╗ █████╗     ████████╗ █████╗ ██╗  ██╗ █████╗ ██╗  ██╗ █████╗ ███████╗██╗  ██╗██╗",
    "     ██║██║   ██║████╗  ██║╚══██╔══╝██╔══██╗    ╚══██╔══╝██╔══██╗██║ ██╔╝██╔══██╗██║  ██║██╔══██╗██╔════╝██║  ██║██║",
    "     ██║██║   ██║██╔██╗ ██║   ██║   ███████║       ██║   ███████║█████╔╝ ███████║███████║███████║███████╗███████║██║",
    "██   ██║██║   ██║██║╚██╗██║   ██║   ██╔══██║       ██║   ██╔══██║██╔═██╗ ██╔══██║██╔══██║██╔══██║╚════██║██╔══██║██║",
    "╚█████╔╝╚██████╔╝██║ ╚████║   ██║   ██║  ██║       ██║   ██║  ██║██║  ██╗██║  ██║██║  ██║██║  ██║███████║██║  ██║██║",
    " ╚════╝  ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝",
]

# Warm, Claude Code-like palettes. Backgrounds stay transparent so the hero
# sits directly on GitHub's page colour in either theme.
THEMES = {
    "dark": {
        "accent": "#D97757",
        "shadow": "#8C4E3A",
        "text": "#E8E6DE",
        "dim": "#8E8C84",
        "rule": "#3A3936",
    },
    "light": {
        "accent": "#C8643F",
        "shadow": "#E8BBA9",
        "text": "#1F1E1D",
        "dim": "#6F6D66",
        "rule": "#DCD9D0",
    },
}

MONO = (
    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, '
    '"Liberation Mono", "DejaVu Sans Mono", monospace'
)

# Canvas and layout (viewBox units).
W, H = 800, 300
BOX_X, BOX_Y, BOX_W, BOX_H, BOX_R = 1.5, 12.0, 797.0, 176.0, 10.0
CELL_W, CELL_H = 6.0, 12.3          # banner cell; ~1:2 like a terminal
BANNER_Y = 46.0
ROLE_Y = 160.0
RULE_TOP, PROMPT_Y, RULE_BOTTOM, STATUS_Y = 212.0, 244.0, 264.0, 288.0

# Prompt line.
PROMPT_FONT = 22.0
PROMPT_CELL = PROMPT_FONT * 0.6     # monospace advance
PROMPT_X = 14.0
TEXT_X = 40.0

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


def banner_svg(theme: dict) -> str:
    width = len(BANNER[0]) * CELL_W
    x0 = (W - width) / 2
    rects: list[str] = []
    strokes: list[str] = []
    g = CELL_W * 0.2  # half distance between the two lines of a double stroke
    last = len(BANNER) - 1
    for r, row in enumerate(BANNER):
        y = BANNER_Y + r * CELL_H
        c = 0
        while c < len(row):
            ch = row[c]
            if ch == "█":
                start = c
                while c < len(row) and row[c] == "█":
                    c += 1
                # Overlap rows slightly so anti-aliasing leaves no seams.
                h = CELL_H + (0.3 if r < last else 0)
                rects.append(
                    f'<rect x="{num(x0 + start * CELL_W)}" y="{num(y)}" '
                    f'width="{num((c - start) * CELL_W)}" height="{num(h)}"/>'
                )
                continue
            l, rt = x0 + c * CELL_W, x0 + (c + 1) * CELL_W
            t, b = y, y + CELL_H
            cx, cy = (l + rt) / 2, (t + b) / 2
            paths = {
                "═": [f"M{num(l)} {num(cy - g)}H{num(rt)}", f"M{num(l)} {num(cy + g)}H{num(rt)}"],
                "║": [f"M{num(cx - g)} {num(t)}V{num(b)}", f"M{num(cx + g)} {num(t)}V{num(b)}"],
                "╗": [f"M{num(l)} {num(cy - g)}H{num(cx + g)}V{num(b)}", f"M{num(l)} {num(cy + g)}H{num(cx - g)}V{num(b)}"],
                "╔": [f"M{num(rt)} {num(cy - g)}H{num(cx - g)}V{num(b)}", f"M{num(rt)} {num(cy + g)}H{num(cx + g)}V{num(b)}"],
                "╝": [f"M{num(cx + g)} {num(t)}V{num(cy + g)}H{num(l)}", f"M{num(cx - g)} {num(t)}V{num(cy - g)}H{num(l)}"],
                "╚": [f"M{num(cx - g)} {num(t)}V{num(cy + g)}H{num(rt)}", f"M{num(cx + g)} {num(t)}V{num(cy - g)}H{num(rt)}"],
            }
            strokes.extend(paths.get(ch, []))
            c += 1
    return (
        f'<path d="{"".join(strokes)}" fill="none" stroke="{theme["shadow"]}" stroke-width="0.9"/>\n'
        f'  <g fill="{theme["accent"]}">{"".join(rects)}</g>'
    )


def box_svg(theme: dict) -> str:
    """Rounded frame with the handle set into the top border."""
    x, y, w, h, r = BOX_X, BOX_Y, BOX_W, BOX_H, BOX_R
    title_font = 14.0
    title_w = len(HANDLE) * title_font * 0.6
    gap_start = x + 18
    star_cx = gap_start + 8 + 6
    text_x = star_cx + 6 + 8
    gap_end = text_x + title_w + 8
    d = (
        f"M{num(gap_end)} {num(y)}H{num(x + w - r)}"
        f"A{num(r)} {num(r)} 0 0 1 {num(x + w)} {num(y + r)}V{num(y + h - r)}"
        f"A{num(r)} {num(r)} 0 0 1 {num(x + w - r)} {num(y + h)}H{num(x + r)}"
        f"A{num(r)} {num(r)} 0 0 1 {num(x)} {num(y + h - r)}V{num(y + r)}"
        f"A{num(r)} {num(r)} 0 0 1 {num(x + r)} {num(y)}H{num(gap_start)}"
    )
    # Eight-spoke asterisk, drawn as strokes so it never falls back to emoji.
    s, k = 5.0, 5.0 * 0.7071
    star = (
        f"M{num(star_cx - s)} {num(y)}H{num(star_cx + s)}"
        f"M{num(star_cx)} {num(y - s)}V{num(y + s)}"
        f"M{num(star_cx - k)} {num(y - k)}L{num(star_cx + k)} {num(y + k)}"
        f"M{num(star_cx - k)} {num(y + k)}L{num(star_cx + k)} {num(y - k)}"
    )
    return (
        f'<path d="{d}" fill="none" stroke="{theme["accent"]}" stroke-width="1.25"/>\n'
        f'  <path d="{star}" fill="none" stroke="{theme["accent"]}" stroke-width="1.6" stroke-linecap="round"/>\n'
        f'  <text x="{num(text_x)}" y="{num(y + 5)}" font-size="{num(title_font)}" font-weight="600" '
        f'fill="{theme["accent"]}" textLength="{num(title_w)}" lengthAdjust="spacing">{escape(HANDLE)}</text>'
    )


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


def prompt_svg(theme: dict) -> tuple[str, str]:
    frames, dur = timeline()
    clips: list[str] = []
    layers: list[str] = []
    cursor_y = PROMPT_Y - PROMPT_FONT * 0.8
    cursor_h = PROMPT_FONT * 1.05

    def text(phrase: str, extra: str = "") -> str:
        return (
            f'<text x="{num(TEXT_X)}" y="{num(PROMPT_Y)}" textLength="{num(len(phrase) * PROMPT_CELL)}" '
            f'lengthAdjust="spacing"{extra}>{escape(phrase)}</text>'
        )

    for i, phrase in enumerate(PHRASES):
        widths = [(t, num(n * PROMPT_CELL if p == i else 0)) for t, p, n, _ in frames]
        clips.append(
            f'<clipPath id="type-{i}"><rect x="{num(TEXT_X)}" y="{num(cursor_y - 4)}" width="0" '
            f'height="{num(cursor_h + 8)}">{discrete("width", widths, dur)}</rect></clipPath>'
        )
        layers.append(f'<g clip-path="url(#type-{i})">{text(phrase)}</g>')

    cursor_x = [(t, num(TEXT_X + n * PROMPT_CELL)) for t, _, n, _ in frames]
    cursor_on = [(t, "1" if on else "0") for t, _, _, on in frames]
    cursor = (
        f'<rect x="{num(TEXT_X)}" y="{num(cursor_y)}" width="{num(PROMPT_CELL - 1.5)}" '
        f'height="{num(cursor_h)}" fill="{theme["text"]}">'
        f'{discrete("x", cursor_x, dur)}{discrete("opacity", cursor_on, dur)}</rect>'
    )
    still = PHRASES[0]
    static = (
        f'<g class="static">{text(still)}'
        f'<rect x="{num(TEXT_X + len(still) * PROMPT_CELL)}" y="{num(cursor_y)}" '
        f'width="{num(PROMPT_CELL - 1.5)}" height="{num(cursor_h)}" fill="{theme["text"]}"/></g>'
    )
    defs = "\n    ".join(clips)
    body = (
        f'<g class="motion">\n    ' + "\n    ".join(layers) + f"\n    {cursor}\n  </g>\n  {static}"
    )
    return defs, body


def build(name: str, theme: dict) -> str:
    defs, prompt = prompt_svg(theme)
    role_size = 22.0
    desc = (
        "Junta Takahashi, AI Agent / RAG Engineer. A terminal prompt types: "
        + "; ".join(PHRASES)
        + "."
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
  <title id="title">Junta Takahashi — AI Agent / RAG Engineer</title>
  <desc id="desc">{escape(desc)}</desc>
  <!-- Generated by scripts/build_hero.py ({name} theme). Edit the script, not this file. -->
  <defs>
    {defs}
  </defs>
  <style>
    text {{ font-family: {MONO}; }}
    .static {{ display: none; }}
    @media (prefers-reduced-motion: reduce) {{
      .motion {{ display: none; }}
      .static {{ display: inline; }}
    }}
  </style>
  {box_svg(theme)}
  {banner_svg(theme)}
  <text x="{num(W / 2)}" y="{num(ROLE_Y)}" text-anchor="middle" font-size="{num(role_size)}" fill="{theme["text"]}">{escape(ROLE[0])} <tspan fill="{theme["accent"]}">/</tspan> {escape(ROLE[1])}</text>
  <path d="M0 {num(RULE_TOP)}H{W}M0 {num(RULE_BOTTOM)}H{W}" stroke="{theme["rule"]}" stroke-width="1"/>
  <text x="{num(PROMPT_X)}" y="{num(PROMPT_Y)}" font-size="{num(PROMPT_FONT)}" fill="{theme["accent"]}">&gt;</text>
  <g font-size="{num(PROMPT_FONT)}" fill="{theme["text"]}">
  {prompt}
  </g>
  <g font-size="12.5" fill="{theme["dim"]}">
    <text x="{num(PROMPT_X + 12)}" y="{num(STATUS_Y)}">{escape(STATUS_LEFT)}</text>
    <text x="{num(W - PROMPT_X - 12)}" y="{num(STATUS_Y)}" text-anchor="end">{escape(STATUS_RIGHT)}</text>
  </g>
</svg>
"""


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        path = OUT_DIR / f"hero-{name}.svg"
        path.write_text(build(name, theme), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
