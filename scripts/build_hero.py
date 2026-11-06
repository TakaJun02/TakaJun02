#!/usr/bin/env python3
"""Generate the hero at the top of README.md and the two buttons under it.

    python3 scripts/build_hero.py

Writes assets/hero.svg, assets/btn-portfolio.svg and assets/btn-x.svg.
Needs numpy, for the characters (through build_agents.py). The CI workflow
never runs it, because the hero does not depend on activity data.

What it draws, inside a Ghostty-style terminal window
- TAKAJUN02 as github.com/srizzon sets its name: Silkscreen capitals at their
  own spacing, every pixel a solid square, in cream. Each column of pixels
  drops in from above with a little bounce, left to right, once on load.
- Clawd at the bottom left and the Codex mark at the bottom right, floating as
  on docs/agents.html: the same renderer (scripts/build_agents.py), the same
  31 ms frames and outline, at three quarters of the page's size, which is
  ghostty.org's own resolution for its ghost. Each turns around once a loop,
  as they do on the page, one after the other. Both are fan art.
- Between them, a Claude Code-style welcome box. Under each character, its
  tool's status line: Claude Code's spinner (· ✢ ✳ ✶ ✻ ✽) and Codex's
  "Working", each with its shimmer.

How it animates
- Every frame of a character is one <text>. CSS shows it for exactly one tick
  (step-end), so the loop plays at the page's frame rate.
- GitHub shows README SVGs as images, so web fonts cannot load. The text uses
  a subset of JetBrains Mono embedded as a data URI (scripts/fonts, SIL Open
  Font License 1.1). Its 0.6 em advance keeps the ASCII cells on the grid.
- prefers-reduced-motion shows the first frame and stops the shimmers and the spinner.
"""

from __future__ import annotations

import base64
import math

import numpy as np
from pathlib import Path
from xml.sax.saxutils import escape

from build_agents import BODY_CELLS, LINE_CELLS, Timeline, render_all, simulate
from build_tj02 import DT, RAMP

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"
FONT_FILE = Path(__file__).resolve().parent / "fonts" / "JetBrainsMono-Regular-subset.woff2"
# The subset holds printable ASCII plus these. To add a character, subset
# JetBrains Mono again with fontTools' pyftsubset and add it here.
FONT_CHARS = {chr(c) for c in range(0x20, 0x7F)} | set("·…•")

# --- Palette: ghostty.org's greys, Claude Code's clay, Codex's blue -----------------
BG = "#0F0F11"
BORDER = "#4C4C50"
TEXT = "#C3C3C4"
MUTED = "#828286"
WHITE = "#FFFFFF"
CLAUDE, CLAUDE_SHIMMER = "#D77757", "#EB9F7F"   # Claude Code: claude / claudeShimmer
CODEX = "#63A8F8"
CREAM = "#E8E6DE"              # this profile's own cream, for the title

# --- Layout ----------------------------------------------------------------------------
W = 1000
LOGO_Y = 72
LOGO_PX = 15                   # px a pixel of the title; srizzon's 11 px, scaled to this wider name
ART_FONT = 8.0                 # px; cells are 0.6 em wide and 1.32 em tall, as on the page
CELL_W, CELL_H = ART_FONT * 0.6, ART_FONT * 1.32
UI_FONT = 11.0                 # px, for the welcome box and the status lines
UI_CW = UI_FONT * 0.6
SCALE = 0.75                   # of docs/agents.html's characters

# --- Timeline ----------------------------------------------------------------------------
LOOP = 240                     # frames: 5 of ghostty.org's 1.5 s bobs, 7.44 s, as long as its loop
TICK = DT
# Each character turns around once a loop, as on docs/agents.html, while the
# other floats and glances its way.
CLAWD_TL = Timeline(n=LOOP, glances=((50, 26, 0.3, 0.05),), blinks=(30, 110, 120, 228),
                    turns=((140, 1),))
CODEX_TL = Timeline(n=LOOP, glances=((180, 26, -0.45, -0.05),), codex=((0, LOOP),),
                    turns=((20, -1),),
                    phase=24)      # half a bob: it rises while Clawd sinks
SPIN_STEP = 0.12               # s per spinner glyph, forwards then backwards

LOGO_TEXT = "TAKAJUN02"
# Silkscreen's zero is its O. A slash keeps the name from reading TAKAJUNO2.
SLASHED_ZERO = (6, "....../..##../.#..#./.#.##./.##.#./..##../......")
# srizzon's drop-in: each column falls 3 pixels and overshoots, 30 ms after the last.
DROP_START, DROP_STEP, DROP_TIME = 0.43, 0.03, 0.35


def fmt(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


# === The logo ===========================================================================

def logo_columns():
    """TAKAJUN02 in Silkscreen at its own advances, as lists of lit rows per pixel column."""
    cols = []
    for ch in LOGO_TEXT:
        adv, bitmap = SLASHED_ZERO if ch == "0" else GLYPHS[ch]
        rows = bitmap.split("/")[1:6]          # the five rows of the capitals
        cols += [[r for r in range(5) if rows[r][c] == "#"] for c in range(adv)]
    while not cols[0]:
        cols.pop(0)
    while not cols[-1]:
        cols.pop()
    return cols


def logo_svg(x0, y0):
    """One group per pixel column, each dropping in after the one to its left."""
    cols = logo_columns()
    groups = []
    for i, lit in enumerate(cols):
        runs, r = [], 0
        while r < 5:
            if r in lit:
                top = r
                while r in lit:
                    r += 1
                runs.append((top, r))
            else:
                r += 1
        if runs:
            rects = "".join(f'<rect x="{x0 + i * LOGO_PX}" y="{y0 + a * LOGO_PX}" width="{LOGO_PX}" height="{(b - a) * LOGO_PX}"/>'
                            for a, b in runs)
            groups.append(f'<g class="dp" style="animation-delay:{DROP_START + i * DROP_STEP:.2f}s">{rects}</g>')
    svg = f'<g fill="{CREAM}" shape-rendering="crispEdges">' + "".join(groups) + "</g>"
    return svg, len(cols) * LOGO_PX, 5 * LOGO_PX


# === Claude Code's spinner glyphs ==========================================================

def rotated(points, a):
    ca, sa = math.cos(a), math.sin(a)
    return [(x * ca - y * sa, x * sa + y * ca) for x, y in points]


def teardrops(n, r, w):
    d = []
    for k in range(n):
        (ax, ay), (bx, by) = rotated([(r - w, -w), (r - w, w)], -math.pi / 2 + 2 * math.pi * k / n)
        d.append(f"M0 0L{fmt(ax)} {fmt(ay)}A{fmt(w)} {fmt(w)} 0 1 1 {fmt(bx)} {fmt(by)}Z")
    return "".join(d)


def spokes(n, r, t):
    d = []
    for k in range(n):
        pts = rotated([(0, -t), (r, -t), (r, t), (0, t)], -math.pi / 2 + 2 * math.pi * k / n)
        d.append("M" + "L".join(f"{fmt(x)} {fmt(y)}" for x, y in pts) + "Z")
    return "".join(d)


def star(n, r, inner):
    pts = []
    for k in range(2 * n):
        a = -math.pi / 2 + math.pi * k / n
        rr = r if k % 2 == 0 else inner
        pts.append((rr * math.cos(a), rr * math.sin(a)))
    return "M" + "L".join(f"{fmt(x)} {fmt(y)}" for x, y in pts) + "Z"


SPINNER = [                    # · ✢ ✳ ✶ ✻ ✽, drawn about the origin in a 12 px cell
    "M-1.6 0a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0 -3.2 0z",
    teardrops(4, 5.4, 1.5),
    spokes(8, 5.4, 0.6),
    star(6, 5.6, 2.4),
    teardrops(8, 5.6, 1.25),
    teardrops(8, 5.8, 1.8),
]

# === The characters ========================================================================

def crop(frames):
    """Cut the loop down to the box that every frame fits in."""
    grids = [f.split("\n") for f in frames]
    used = [(r, row) for g in grids for r, row in enumerate(g) if row.strip()]
    top, bottom = min(r for r, _ in used), max(r for r, _ in used)
    left = min(len(row) - len(row.lstrip()) for _, row in used)
    right = max(len(row) for _, row in used)
    return [[row[left:] for row in g[top:bottom + 1]] for g in grids], right - left, bottom - top + 1


# Frames are laid out at 10 px and scaled down to ART_FONT, so every column
# lands on a whole number (0.6 em = 6 units) and the file stays smaller.
INNER_FONT = 10
INNER_CW, INNER_CH, INNER_BASE = 6, 13.2, 10.2


def layer(rows, cells):
    """One colour of a frame: a tspan per stretch of each row. Gaps shorter
    than a tspan's markup stay as spaces; the font is monospace."""
    out = []
    for r, row in enumerate(rows):
        line = "".join(RAMP[cells.index(ch)] if ch in cells else " " for ch in row)
        runs, c = [], 0
        while c < len(line):
            if line[c] == " ":
                c += 1
                continue
            s = c
            while c < len(line) and line[c] != " ":
                c += 1
            if runs and s - runs[-1][1] < 20:
                runs[-1][1] = c
            else:
                runs.append([s, c])
        for k, (s, e) in enumerate(runs):
            y = f' y="{fmt(r * INNER_CH + INNER_BASE)}"' if k == 0 else ""
            out.append(f'<tspan x="{s * INNER_CW}"{y}>{line[s:e]}</tspan>')
    return "".join(out)


def frame_group(rows, cls, fid, delay):
    """One frame: the character in its colour and the outline in white."""
    return (f'<g id="{fid}" class="f" style="animation-delay:{delay:.3f}s">'
            f'<text class="{cls}">{layer(rows, BODY_CELLS)}</text>'
            f'<text class="o">{layer(rows, LINE_CELLS)}</text></g>')


def character(frames, cls, prefix, x, y):
    rows, _, _ = crop(frames)
    body = "".join(frame_group(g, cls, f"{prefix}{i}", i * TICK) for i, g in enumerate(rows))
    return f'<g transform="translate({fmt(x)} {fmt(y)}) scale({fmt(ART_FONT / INNER_FONT)})">{body}</g>'

# === Text ==================================================================================

def text(x, y, s, size, fill, anchor=None, extra=""):
    assert set(s) <= FONT_CHARS, set(s) - FONT_CHARS
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{fmt(size)}" fill="{fill}"{a}{extra}>{escape(s)}</text>'


def spans(x, y, pieces, size):
    """Several coloured pieces on one line, laid out on the monospace grid."""
    out, cw = [], size * 0.6
    for s, fill in pieces:
        if s.strip():
            out.append(text(x, y, s, size, fill))
        x += len(s) * cw
    return "".join(out)


def shimmer(cid, x, y, s, size, fill, glow, period, width=3, step=0.07):
    """Claude Code's shimmer: a few cells of a lighter colour stepping across
    the text one cell at a time, then a pause."""
    cw = size * 0.6
    steps = len(s) + width
    run = steps * step
    pct = 100 * run / period
    css = (f".{cid}{{animation:{cid} {period:g}s infinite}}"
           f"@keyframes {cid}{{0%{{transform:translateX(0);animation-timing-function:steps({steps},end)}}"
           f"{pct:.2f}%,100%{{transform:translateX({fmt(steps * cw)}px)}}}}")
    svg = (text(x, y, s, size, fill) +
           f'<clipPath id="{cid}c">{text(x, y, s, size, fill)}</clipPath>'
           f'<g clip-path="url(#{cid}c)"><rect class="{cid}" x="{fmt(x - width * cw)}" y="{fmt(y - size)}" '
           f'width="{fmt(width * cw)}" height="{fmt(size * 1.4)}" fill="{glow}"/></g>')
    return svg, css


def spinner(cx, cy, scale, fill):
    out = [f'<g transform="translate({fmt(cx)} {fmt(cy)}) scale({fmt(scale)})" fill="{fill}">']
    seq = list(range(len(SPINNER))) + list(reversed(range(len(SPINNER))))
    for k, g in enumerate(seq):
        out.append(f'<path id="sp{k}" class="sp" d="{SPINNER[g]}" style="animation-delay:{k * SPIN_STEP:.2f}s"/>')
    out.append("</g>")
    css = (f".sp{{visibility:hidden;animation:sp {len(seq) * SPIN_STEP:.2f}s step-end infinite}}"
           f"@keyframes sp{{0%{{visibility:visible}}{100 / len(seq):.4f}%{{visibility:hidden}}}}")
    return "".join(out), css

# === Hero ==================================================================================

def build_hero():
    clawd_poses, codex_poses = simulate(CLAWD_TL), simulate(CODEX_TL)
    for p in clawd_poses + codex_poses:
        p["scale"] = SCALE
    frames = render_all(clawd_poses + codex_poses)
    clawd, codex = frames[:LOOP], frames[LOOP:]
    _, clawd_w, clawd_h = crop(clawd)
    _, codex_w, codex_h = crop(codex)
    clawd_w, clawd_h = clawd_w * CELL_W, clawd_h * CELL_H
    codex_w, codex_h = codex_w * CELL_W, codex_h * CELL_H
    art_h = max(clawd_h, codex_h)
    _, logo_w, logo_h = logo_svg(0, 0)
    tagline_y = LOGO_Y + logo_h + 36
    art_top = tagline_y + 26
    H = round(art_top + art_h + 62)
    art_mid = art_top + art_h / 2
    clawd_cx, codex_cx = 188, 814
    clawd_x, clawd_y = clawd_cx - clawd_w / 2, art_mid - clawd_h / 2
    codex_x, codex_y = codex_cx - codex_w / 2, art_mid - codex_h / 2
    status_y = art_top + art_h + 30

    css = [
        f'@font-face{{font-family:J;src:url(data:font/woff2;base64,{base64.b64encode(FONT_FILE.read_bytes()).decode()}) format("woff2")}}',
        "text{font-family:J,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre}",
        f".f{{font-size:{INNER_FONT}px;visibility:hidden;animation:f {LOOP * TICK:.3f}s step-end infinite}}",
        f"@keyframes f{{0%{{visibility:visible}}{100 / LOOP:.4f}%{{visibility:hidden}}}}",
        f".c{{fill:{CLAUDE}}}.x{{fill:{CODEX}}}.o{{fill:{TEXT}}}",
        f".dp{{opacity:0;animation:dp {DROP_TIME}s cubic-bezier(.3,1.4,.6,1) both}}"
        f"@keyframes dp{{from{{opacity:0;transform:translateY({-3 * LOGO_PX}px)}}to{{opacity:1;transform:none}}}}",
    ]
    out = []

    # Ghostty-style window: hairline border, traffic lights, centred title.
    out.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>')
    for i, c in enumerate(("#FF605C", "#FFBD44", "#00CA4E")):
        out.append(f'<circle cx="{20 + i * 20}" cy="19" r="6" fill="{c}"/>')
    title = "takajun02"
    tx = W / 2 - (len(title) + 2) * 13 * 0.6 / 2
    out.append(f'<path transform="translate({fmt(tx + 4)} 18.5) scale(0.62)" fill="{CLAUDE}" d="{SPINNER[4]}"/>')
    out.append(text(tx + 2 * 13 * 0.6, 23, title, 13, MUTED))

    # TAKAJUN02.
    out.append(logo_svg(round((W - logo_w) / 2), LOGO_Y)[0])

    out.append(text(W / 2, tagline_y, "AI agent architect · software engineer", 16, TEXT, anchor="middle"))

    # Clawd and the Codex mark.
    out.append(character(clawd, "c", "c", clawd_x, clawd_y))
    out.append(character(codex, "x", "x", codex_x, codex_y))

    # A Claude Code-style welcome box between them.
    lines_ = [("✻ ", "Welcome to TakaJun02's GitHub!"),
              ("", ""),
              ("  ", "/portfolio for work, /x for updates"),
              ("", ""),
              ("  ", "cwd: ~/akita/ai-agents")]
    box_cols = max(len(a + b) for a, b in lines_) + 4
    box_w, line_h = box_cols * UI_CW, UI_FONT * 1.5
    box_h = len(lines_) * line_h + 16
    bx, by = W / 2 - box_w / 2, art_mid - box_h / 2
    out.append(f'<rect x="{fmt(bx)}" y="{fmt(by)}" width="{fmt(box_w)}" height="{fmt(box_h)}" rx="7" fill="none" stroke="{CLAUDE}"/>')
    tx0 = bx + 2 * UI_CW
    for i, (lead, body) in enumerate(lines_):
        y = by + 8 + (i + 0.78) * line_h
        if lead == "✻ ":
            out.append(f'<path transform="translate({fmt(tx0 + UI_CW / 2)} {fmt(y - UI_FONT * 0.36)}) scale(0.6)" fill="{CLAUDE}" d="{SPINNER[4]}"/>')
            out.append(spans(tx0 + 2 * UI_CW, y, [("Welcome to ", TEXT), ("TakaJun02", WHITE), ("'s GitHub!", TEXT)], UI_FONT))
        elif body.startswith("/"):
            out.append(spans(tx0 + 2 * UI_CW, y, [("/portfolio", TEXT), (" for work, ", MUTED), ("/x", TEXT), (" for updates", MUTED)], UI_FONT))
        elif body:
            out.append(spans(tx0 + 2 * UI_CW, y, [(body, MUTED)], UI_FONT))

    # Under Clawd, Claude Code's status line; under the Codex mark, Codex's.
    a_word, a_rest = "Building agents…", " (esc to interrupt)"
    a_x = clawd_cx - (2 + len(a_word + a_rest)) * UI_CW / 2
    sp, sp_css = spinner(a_x + UI_CW / 2, status_y - UI_FONT * 0.36, 0.62, CLAUDE)
    out.append(sp)
    css.append(sp_css)
    word, word_css = shimmer("s1", a_x + 2 * UI_CW, status_y, a_word, UI_FONT, CLAUDE, CLAUDE_SHIMMER, 2.6)
    out.append(word)
    css.append(word_css)
    out.append(spans(a_x + (2 + len(a_word)) * UI_CW, status_y, [(a_rest, MUTED)], UI_FONT))

    b_word, b_rest = "Working", " (12s • esc to interrupt)"
    b_x = codex_cx - (2 + len(b_word + b_rest)) * UI_CW / 2
    out.append(spans(b_x, status_y, [("•", CODEX)], UI_FONT))
    word, word_css = shimmer("s2", b_x + 2 * UI_CW, status_y, b_word, UI_FONT, TEXT, WHITE, 2.2)
    out.append(word)
    css.append(word_css)
    out.append(spans(b_x + (2 + len(b_word)) * UI_CW, status_y, [(b_rest, MUTED)], UI_FONT))

    css.append("@media (prefers-reduced-motion:reduce){.f,.sp,.s1,.s2,.dp{animation:none!important}"
               ".dp{opacity:1}#c0,#x0,#sp8{visibility:visible}}")
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" xml:space="preserve">',
           "<!-- TAKAJUN02 in Silkscreen by Jason Kottke (SIL Open Font License 1.1), set as github.com/srizzon sets its name. Clawd (Claude Code, Anthropic) and the Codex mark (OpenAI)\n"
           "     are fan art, rendered by scripts/build_agents.py after ghostty.org's terminal animation\n"
           "     (github.com/ghostty-org/website, MIT). Text is set in a subset of JetBrains Mono,\n"
           "     Copyright 2020 The JetBrains Mono Project Authors, SIL Open Font License 1.1. -->",
           f"<style>{''.join(css)}</style>"] + out + ["</svg>"]
    return "".join(svg), H


# === Buttons ===============================================================================
# The buttons keep the pixel style of the earlier hero.

BTN_BG = "#141413"
BTN_WINDOW = "#1A1918"
BTN_BORDER = "#3D3D3A"
BTN_CREAM = "#E8E6DC"
CLAY = "#D97757"
CLAY_SHADOW = "#7A3E28"


def text_width(text, scale, track=1):
    return sum(GLYPHS[ch][0] + track for ch in text) * scale - track * scale - scale


def pixel_path(text, x, y, scale, track=1):
    """Silkscreen text as one path. (x, y) is the top-left of the capitals."""
    parts = []
    cx = x - scale                       # glyphs carry a 1px left bearing
    for ch in text:
        adv, bitmap = GLYPHS[ch]
        for ri, row in enumerate(bitmap.split("/")):
            c = 0
            while c < len(row):
                if row[c] == "#":
                    start = c
                    while c < len(row) and row[c] == "#":
                        c += 1
                    w = (c - start) * scale
                    parts.append(f"M{cx + start * scale:g} {y + (ri - 1) * scale:g}h{w:g}v{scale:g}h{-w:g}z")
                else:
                    c += 1
        cx += (adv + track) * scale
    return "".join(parts)


def pixel_text(text, x, y, scale, fill, track=1, anchor="start"):
    text = text.upper()
    if anchor == "middle":
        x = x - text_width(text, scale, track) / 2
    return f'<path fill="{fill}" d="{pixel_path(text, round(x), y, scale, track)}"/>', text_width(text, scale, track)


def button(label, fill, ink, shadow, border=None):
    scale = 2
    tw = text_width(label.upper(), scale)
    w, h = round(tw + 56), 44
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w + 4} {h + 4}" width="{w + 4}" height="{h + 4}">',
             f'<rect x="4" y="4" width="{w}" height="{h}" fill="{shadow}"/>',
             f'<rect width="{w}" height="{h}" fill="{fill}"' + (f' stroke="{border}" stroke-width="2"' if border else "") + "/>",
             pixel_text(label, w / 2, 17, scale, ink, anchor="middle")[0],
             "</svg>"]
    return "".join(parts)


def main():
    hero, height = build_hero()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "hero.svg").write_text(hero, encoding="utf-8")
    (OUT_DIR / "btn-portfolio.svg").write_text(button("portfolio >", CLAY, BTN_BG, CLAY_SHADOW), encoding="utf-8")
    (OUT_DIR / "btn-x.svg").write_text(button("x  @juntatakahashi0", BTN_WINDOW, BTN_CREAM, "#000000", border=BTN_BORDER), encoding="utf-8")
    kb = (OUT_DIR / "hero.svg").stat().st_size / 1024
    print(f"hero.svg: {W}x{height}, {LOOP} frames a character, {LOOP * TICK:.2f}s loop, {kb:.0f} KB")


# Silkscreen by Jason Kottke (SIL Open Font License 1.1), rasterised at 8px.
# Each entry is (advance, rows); rows run from one pixel above the capitals to
# one below, '#' marks a lit pixel.
GLYPHS = {
    ' ': (4, '..../..../..../..../..../..../....'),
    '!': (3, '.../.#./.#./.#./.../.#./...'),
    '"': (5, '...../.#.#./.#.#./...../...../...../.....'),
    '#': (7, '......./..#.#../.#####./..#.#../.#####./..#.#../.......'),
    '$': (6, '...#../..###./.#..../..##../....#./.###../..#...'),
    '%': (7, '......./.##.#../.##.#../...#.../..#.##./..#.##./.......'),
    '&': (6, '...#../..###./.#..../..##../.#..../..###./...#..'),
    "'": (3, '.../.#./.#./.../.../.../...'),
    '(': (4, '..../..#./.#../.#../.#../..#./....'),
    ')': (4, '..../.#../..#./..#./..#./.#../....'),
    '*': (7, '......./...#.../.#.#.#./..###../.#.#.#./...#.../.......'),
    '+': (7, '......./...#.../...#.../.#####./...#.../...#.../.......'),
    ',': (4, '..../..../..../..../..#./.#../....'),
    '-': (5, '...../...../...../.###./...../...../.....'),
    '.': (3, '.../.../.../.../.#./.../...'),
    '/': (5, '...../...#./...#./..#../.#.../.#.../.....'),
    '0': (6, '....../..##../.#..#./.#..#./.#..#./..##../......'),
    '1': (5, '...../.##../..#../..#../..#../.###./.....'),
    '2': (6, '....../.###../....#./..##../.#..../.####./......'),
    '3': (6, '....../.###../....#./..##../....#./.###../......'),
    '4': (6, '....../.#.#../.#.#../.####./...#../...#../......'),
    '5': (6, '....../.####./.#..../.###../....#./.###../......'),
    '6': (6, '....../..##../.#..../.###../.#..#./..##../......'),
    '7': (6, '....../.####./....#./...#../..#.../..#.../......'),
    '8': (6, '....../..##../.#..#./..##../.#..#./..##../......'),
    '9': (6, '....../..##../.#..#./..###./....#./..##../......'),
    ':': (3, '.../.../.#./.../.#./.../...'),
    ';': (4, '..../..../..#./..../..#./.#../....'),
    '<': (5, '...../...#./..#../.#.../..#../...#./.....'),
    '=': (5, '...../...../.###./...../.###./...../.....'),
    '>': (5, '...../.#.../..#../...#./..#../.#.../.....'),
    '?': (6, '....../.###../....#./..##../....../..#.../......'),
    '@': (7, '......./..###../.#.#.#./.#.##../.#...../..###../.......'),
    'A': (6, '....../..##../.#..#./.####./.#..#./.#..#./......'),
    'B': (6, '....../.###../.#..#./.####./.#..#./.###../......'),
    'C': (6, '....../..##../.#..#./.#..../.#..#./..##../......'),
    'D': (6, '....../.###../.#..#./.#..#./.#..#./.###../......'),
    'E': (5, '...../.###./.#.../.###./.#.../.###./.....'),
    'F': (5, '...../.###./.#.../.###./.#.../.#.../.....'),
    'G': (6, '....../..###./.#..../.#.##./.#..#./..##../......'),
    'H': (6, '....../.#..#./.#..#./.####./.#..#./.#..#./......'),
    'I': (3, '.../.#./.#./.#./.#./.#./...'),
    'J': (6, '....../....#./....#./....#./.#..#./..##../......'),
    'K': (6, '....../.#..#./.#.#../.##.../.#.#../.#..#./......'),
    'L': (5, '...../.#.../.#.../.#.../.#.../.###./.....'),
    'M': (7, '......./.#...#./.##.##./.#.#.#./.#...#./.#...#./.......'),
    'N': (7, '......./.#...#./.##..#./.#.#.#./.#..##./.#...#./.......'),
    'O': (6, '....../..##../.#..#./.#..#./.#..#./..##../......'),
    'P': (6, '....../.###../.#..#./.###../.#..../.#..../......'),
    'Q': (6, '....../..##../.#..#./.#..#./.#..#./..##../....#.'),
    'R': (6, '....../.###../.#..#./.###../.#.#../.#..#./......'),
    'S': (6, '....../..###./.#..../..##../....#./.###../......'),
    'T': (5, '...../.###./..#../..#../..#../..#../.....'),
    'U': (6, '....../.#..#./.#..#./.#..#./.#..#./..##../......'),
    'V': (7, '......./.#...#./.#...#./..#.#../..#.#../...#.../.......'),
    'W': (7, '......./.#...#./.#.#.#./.#.#.#./.#.#.#./..#.#../.......'),
    'X': (7, '......./.#...#./..#.#../...#.../..#.#../.#...#./.......'),
    'Y': (7, '......./.#...#./..#.#../...#.../...#.../...#.../.......'),
    'Z': (5, '...../.###./...#./..#../.#.../.###./.....'),
    '[': (4, '..../.##./.#../.#../.#../.##./....'),
    '\\': (5, '...../.#.../.#.../..#../...#./...#./.....'),
    ']': (4, '..../.##./..#./..#./..#./.##./....'),
    '^': (5, '..#../.#.#./...../...../...../...../.....'),
    '_': (6, '....../....../....../....../....../....../.####.'),
    '`': (4, '..../..../..../..../..../..../....'),
    '{': (5, '...../..##./..#../.#.../..#../..##./.....'),
    '|': (3, '.#./.#./.#./.#./.#./.#./.#.'),
    '}': (5, '...../.##../..#../...#./..#../.##../.....'),
    '~': (6, '....../..#.#./.#.#../....../....../....../......'),
    '·': (3, '.../.../.../.#./.../.../...'),
    '•': (3, '.../.../.../.#./.../.../...'),
    '…': (7, '......./......./......./......./.#.#.#./......./.......'),
}

if __name__ == "__main__":
    main()
