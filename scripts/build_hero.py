#!/usr/bin/env python3
"""Generate the hero image at the top of README.md and the two buttons under it.

    python3 scripts/build_hero.py

Writes assets/hero.svg, assets/btn-portfolio.svg and assets/btn-x.svg.
Needs numpy. Only this script uses it, and the CI workflow never runs it,
because the hero does not depend on activity data.

What it draws
- A Ghostty-style terminal window (after ghostty.org). Inside it, Clawd from
  Claude Code and the Codex mark take turns spinning in 3D, drawn as ASCII the
  way ghostty.org draws its ghost: one ray per character cell, Lambert shading,
  and the 10-step luminance ramp from ghostty-org/website's
  bin/video-to-terminal/video-to-terminal.sh (MIT).
- Around it, Git City's UI language (after thegitcity.com): Silkscreen pixel
  type drawn as paths, dark panels, hard offset shadows, HUD chips and an
  activity ticker. GitHub shows README SVGs as images, so web fonts never load;
  GLYPHS below holds Silkscreen's bitmaps at its native 8px size (OFL-1.1).
- Clawd follows the quadrant-pixel layout that Claude Code prints. The Codex
  mark uses the path in openai/codex codex-rs/tui/src/empty_state_animation/
  paths.rs. Both are fan art of other people's characters. The README says so
  under the image.

How it animates
- Each distinct frame is a <g> in <defs>. The timeline is a row of <use>
  slots, one per TICK; CSS shows each slot for exactly one tick (step-end), so
  a held pose reuses its frame and costs no extra bytes.
- Clawd blinks while it holds still, the Codex cursor (the `_`) blinks while it
  holds still, and the two characters swap through a short dissolve.
- Every glyph in a monospace font has the same advance, so the rows stay
  aligned in whichever monospace font the viewer has.
- prefers-reduced-motion shows Clawd's first frame and stops the ticker.
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"

# --- Palette: Anthropic's warm grays plus each tool's own accent ---------------
BG = "#141413"         # card
WINDOW = "#1A1918"     # terminal window
BORDER = "#3D3D3A"
DOT = "#262624"        # card dot grid
CREAM = "#E8E6DC"
MUTED = "#87867F"
DIM = "#5E5D59"
CLAY = "#D97757"
CLAY_SHADOW = "#7A3E28"
LIVE = "#4EBA65"
CLAWD_BASE, CLAWD_HI = "#D77757", "#EB9F7F"   # Claude Code: claude / claudeShimmer
CODEX_BASE, CODEX_HI = "#63A8F8", "#D2DDEB"   # Codex: UI accent / logo key light

# --- ASCII renderer --------------------------------------------------------------
RAMP = "·~ox+=*%$@"    # ghostty.org's ramp, darkest to brightest
COLS, ROWS = 76, 30
CELL_W, CELL_H = 7.2, 13.0
FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
TILT = math.radians(-14)          # look at the characters a little from above
LIGHT_POS = np.array([-14.0, 13.0, -22.0])   # a point light up and to the left of the camera

# --- Timeline (in ticks) -----------------------------------------------------------
TICK = 0.09            # seconds per frame
SPIN = 30              # frames per full turn (12 degrees each)
HOLD_FRONT = 12
HOLD_AFTER = 6
DISSOLVE = 4


# === Scene ===========================================================================

def sd_box(p, center, half, r=0.12):
    q = np.abs(p - np.asarray(center)) - (np.asarray(half) - r)
    return np.linalg.norm(np.maximum(q, 0.0), axis=1) + np.minimum(q.max(axis=1), 0.0) - r


def sd_segment2(x, y, a, b):
    pa = np.stack([x - a[0], y - a[1]], axis=1)
    ba = np.array([b[0] - a[0], b[1] - a[1]])
    h = np.clip((pa @ ba) / (ba @ ba), 0.0, 1.0)
    return np.linalg.norm(pa - h[:, None] * ba, axis=1)


class Clawd:
    """Clawd as boxes. One terminal quadrant pixel is 1 wide and 2 tall."""

    depth = 7.0
    scale = 0.29            # world units per column
    base, hi = CLAWD_BASE, CLAWD_HI

    def __init__(self, blink=False):
        d = self.depth / 2
        self.parts = [
            ((0, 1, 0), (6.5, 4, d)),            # body: pixel rows 0-3, columns 3-15
            ((-7.5, 0, 0), (1, 1, 1.5)),         # arms: row 2, columns 1-2 and 16-17
            ((7.5, 0, 0), (1, 1, 1.5)),
        ]
        for x in (-6, -4, 4, 6):                 # legs: row 4, columns 3, 5, 13, 15
            for z in (-d + 0.5, d - 0.5):        # a front pair and a back pair
                self.parts.append(((x, -4, z), (0.5, 1, 0.5)))
        # Eyes are sockets carved into the front face (row 1, columns 5 and 13).
        # A closed eye leaves only a thin slit at the bottom, like Claude Code's `▂`.
        eye_y, eye_h = ((1.25, 0.25) if blink else (2.0, 1.0))
        self.eyes = [((x, eye_y, -d), (0.5, eye_h, 0.6)) for x in (-4, 4)]

    def sdf(self, p):
        body = np.min([sd_box(p, c, h) for c, h in self.parts], axis=0)
        eyes = np.min([sd_box(p, c, h, r=0.02) for c, h in self.eyes], axis=0)
        return np.maximum(body, -eyes)

    def material(self, p):
        eyes = np.min([sd_box(p, c, h, r=0.02) for c, h in self.eyes], axis=0)
        return np.where(eyes < 0.08, "eye", "body")


class CodexMark:
    """The Codex mark (ring, `>` and `_`) extruded into a thick coin."""

    depth = 2.2
    scale = 0.34
    base, hi = CODEX_BASE, CODEX_HI
    half_stroke = 0.665

    def __init__(self, cursor=True):
        self.cursor = cursor

    def sdf(self, p):
        # paths.rs works in a 20x20 box with y pointing down; centre it, y up.
        x, y, z = p[:, 0] + 10.0, 10.0 - p[:, 1], p[:, 2]
        hs = self.half_stroke
        ring = np.abs(np.hypot(x - 10.0, y - 10.0) - 7.25) - hs
        chevron = np.minimum(sd_segment2(x, y, (7.083, 7.917), (8.23, 10.0)),
                             sd_segment2(x, y, (8.23, 10.0), (7.083, 12.083))) - hs
        shape = np.minimum(ring, chevron)
        if self.cursor:
            shape = np.minimum(shape, sd_segment2(x, y, (10.833, 12.083), (13.333, 12.083)) - hs)
        wz = np.abs(z) - self.depth / 2
        w = np.stack([shape, wz], axis=1)
        return np.minimum(w.max(axis=1), 0.0) + np.linalg.norm(np.maximum(w, 0.0), axis=1)

    def material(self, p):
        return np.full(len(p), "body", dtype=object)


def rotation(yaw, tilt):
    cy, sy, ct, st = math.cos(yaw), math.sin(yaw), math.cos(tilt), math.sin(tilt)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])
    return rx @ ry


def render(model, yaw):
    """Return a ROWS x COLS grid of (char, colour) cells, or None for empty."""
    s = model.scale
    cols = (np.arange(COLS) + 0.5 - COLS / 2) * s
    rows = (ROWS / 2 - np.arange(ROWS) - 0.5) * s * (CELL_H / CELL_W)
    u, v = np.meshgrid(cols, rows)
    origin = np.stack([u.ravel(), v.ravel(), np.full(u.size, -30.0)], axis=1)
    rot = rotation(yaw, TILT)
    inv = rot.T
    o = origin @ inv.T
    d = np.array([0.0, 0.0, 1.0]) @ inv.T
    t = np.zeros(len(o))
    alive = np.ones(len(o), dtype=bool)
    hit = np.zeros(len(o), dtype=bool)
    for _ in range(96):
        p = o[alive] + t[alive, None] * d
        dist = model.sdf(p)
        idx = np.flatnonzero(alive)
        done = dist < 2e-3
        hit[idx[done]] = True
        t[idx] += dist
        alive[idx[done | (t[idx] > 60)]] = False
        if not alive.any():
            break
    grid = [[None] * COLS for _ in range(ROWS)]
    if not hit.any():
        return grid
    hi_idx = np.flatnonzero(hit)
    p = o[hi_idx] + t[hi_idx, None] * d
    e = 0.01
    n = np.stack([model.sdf(p + [e, 0, 0]) - model.sdf(p - [e, 0, 0]),
                  model.sdf(p + [0, e, 0]) - model.sdf(p - [0, e, 0]),
                  model.sdf(p + [0, 0, e]) - model.sdf(p - [0, 0, e])], axis=1)
    n = n / np.linalg.norm(n, axis=1, keepdims=True)
    n_cam = n @ rot.T
    to_light = LIGHT_POS - p @ rot.T
    to_light /= np.linalg.norm(to_light, axis=1, keepdims=True)
    diffuse = np.clip(np.sum(n_cam * to_light, axis=1), 0.0, 1.0)
    rim = (1.0 - np.abs(n_cam[:, 2])) ** 2 * 0.18
    lum = np.clip(0.10 + 0.86 * diffuse + rim, 0.0, 0.999)
    mat = model.material(p)
    for k, i in enumerate(hi_idx):
        r, c = divmod(int(i), COLS)
        if mat[k] == "eye":
            continue                      # sockets read as black eyes
        level = int(lum[k] * len(RAMP))
        grid[r][c] = (RAMP[level], "h" if level >= 8 else "")
    return grid


def tag(grid, who):
    """Mark each cell with its character ("a" Clawd, "b" Codex) for dissolves."""
    return [[(ch, f"{who} {cls}".strip()) if cell else None
             for cell in row for ch, cls in [cell or (" ", "")]] for row in grid]


def dissolve(a, b, steps, seed):
    rng = random.Random(seed)
    frames = []
    for k in range(1, steps + 1):
        p = k / (steps + 1)
        noise = 0.38 * math.sin(math.pi * p)
        g = [[None] * COLS for _ in range(ROWS)]
        for r in range(ROWS):
            for c in range(COLS):
                src = b[r][c] if rng.random() < p else a[r][c]
                if (src or a[r][c] or b[r][c]) and rng.random() < noise:
                    src = (rng.choice(RAMP), "n")
                g[r][c] = src
        frames.append(g)
    return frames


# === SVG pieces ======================================================================

def frame_group(fid, grid, base, y0):
    """One frame. The group sets the base colour; tspans mark highlights ("h")
    and dissolve noise ("n"). Every glyph in a monospace font has the same
    advance, so rows stay aligned in any font without textLength."""
    out = [f'<g id="{fid}" class="{base}">']
    for r, row in enumerate(grid):
        last = max((c for c, cell in enumerate(row) if cell), default=-1)
        if last < 0:
            continue
        runs, colour, buf = [], None, []
        for cell in row[: last + 1]:
            ch, col = cell if cell else (" ", colour)
            if col != colour and buf:
                runs.append((colour, "".join(buf)))
                buf = []
            colour = col
            buf.append(ch)
        runs.append((colour, "".join(buf)))
        spans = "".join(f'<tspan class="{c}">{escape(t)}</tspan>' if c else escape(t) for c, t in runs)
        y = y0 + (r + 1) * CELL_H - 3
        out.append(f'<text y="{y:.0f}">{spans}</text>')
    out.append("</g>")
    return "".join(out)


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


def pixel_line(pieces, cx, y, scale, track=1):
    """Centre several differently coloured pieces on one line. Pieces carry
    their own spaces, so "takajun" + "02" stays one word."""
    step = track * scale + scale                  # what text_width trims per piece
    total = sum(text_width(t.upper(), scale, track) + step for t, _ in pieces) - step
    x = cx - total / 2
    out = []
    for t, fill in pieces:
        svg, w = pixel_text(t, x, y, scale, fill, track)
        out.append(svg)
        x += w + step
    return "".join(out)


def chip(x, y, label, scale=2, dot=None, align="left"):
    w = text_width(label.upper(), scale) + 24 + (14 if dot else 0)
    if align == "right":
        x = x - w
    body = [f'<rect x="{x}" y="{y}" width="{w:.0f}" height="26" fill="{WINDOW}" stroke="{BORDER}"/>']
    tx = x + 12
    if dot:
        body.append(f'<rect class="live" x="{tx}" y="{y + 10}" width="6" height="6" fill="{dot}"/>')
        tx += 14
    body.append(pixel_text(label, tx, y + 8, scale, CREAM)[0])
    return "".join(body)


# === Hero ============================================================================

def build_hero():
    clawd_open = render(Clawd(), 0.0)
    clawd_blink = render(Clawd(blink=True), 0.0)
    codex_on = render(CodexMark(), 0.0)
    codex_off = render(CodexMark(cursor=False), 0.0)
    frames = {"a0": clawd_open, "a1": clawd_blink, "b0": codex_on, "b1": codex_off}
    for i in range(1, SPIN):
        yaw = 2 * math.pi * i / SPIN
        frames[f"as{i}"] = render(Clawd(), yaw)
        frames[f"bs{i}"] = render(CodexMark(), yaw)
    owner = {fid: ("cb" if fid.startswith("b") else "ca") for fid in frames}
    # Dissolves keep each cell's own colour: Clawd's cells in clay, Codex's in blue.
    for i, g in enumerate(dissolve(tag(clawd_open, "a"), tag(codex_on, "b"), DISSOLVE, seed=2)):
        frames[f"ab{i}"] = g
        owner[f"ab{i}"] = "cm"
    for i, g in enumerate(dissolve(tag(codex_on, "b"), tag(clawd_open, "a"), DISSOLVE, seed=5)):
        frames[f"ba{i}"] = g
        owner[f"ba{i}"] = "cm"

    def act(front, alt, spin, alt_ticks):
        seq = [alt if t in alt_ticks else front for t in range(HOLD_FRONT)]
        seq += [f"{spin}{i}" for i in range(1, SPIN)] + [front] * HOLD_AFTER
        return seq

    timeline = act("a0", "a1", "as", {6, 7})
    timeline += [f"ab{i}" for i in range(DISSOLVE)]
    swap_to_codex = len(timeline) - DISSOLVE // 2
    timeline += act("b0", "b1", "bs", {4, 5, 6, 7, 8, 9})
    timeline += [f"ba{i}" for i in range(DISSOLVE)]
    swap_to_clawd = len(timeline) - DISSOLVE // 2
    n = len(timeline)
    period = n * TICK
    slot_pct = 100 / n
    p1, p2 = 100 * swap_to_codex / n, 100 * swap_to_clawd / n

    W, H = 960, 664
    win_w = round(COLS * CELL_W + 36)
    win_h = 34 + ROWS * CELL_H + 18
    win_x, win_y = (W - win_w) // 2, 172
    art_x, art_y = win_x + 18, win_y + 34

    ticker_msgs = ["clawd is moonwalking…", "codex · working (12s • esc to interrupt)",
                   "tj-02 is counting today's contributions", "clawd is flibbertigibbeting…",
                   "codex · updated plan · 2/3 complete", "clawd is percolating…"]
    ticker = "  ·  ".join(ticker_msgs) + "  ·  "
    tick_w = text_width(ticker.upper(), 2) + (GLYPHS[" "][0] + 1) * 2
    TICK_X = round(34 + text_width("AGENT ACTIVITY", 2) + 20)

    css = f"""
.s{{visibility:hidden;animation:tl {period:.2f}s step-end infinite}}
@keyframes tl{{0%{{visibility:visible}}{slot_pct:.4f}%{{visibility:hidden}}}}
.ta{{animation:ta {period:.2f}s step-end infinite}}
@keyframes ta{{0%{{visibility:visible}}{p1:.3f}%{{visibility:hidden}}{p2:.3f}%{{visibility:visible}}}}
.tb{{visibility:hidden;animation:tb {period:.2f}s step-end infinite}}
@keyframes tb{{0%{{visibility:hidden}}{p1:.3f}%{{visibility:visible}}{p2:.3f}%{{visibility:hidden}}}}
.tk{{animation:tk {tick_w / 40:.1f}s linear infinite}}
@keyframes tk{{to{{transform:translateX(-{tick_w:.0f}px)}}}}
.live{{animation:lv 1.6s steps(2) infinite}}
.ca{{fill:{CLAWD_BASE}}}.cb{{fill:{CODEX_BASE}}}.cm{{fill:{DIM}}}
.ca .h,.a.h{{fill:{CLAWD_HI}}}.cb .h,.b.h{{fill:{CODEX_HI}}}.a{{fill:{CLAWD_BASE}}}.b{{fill:{CODEX_BASE}}}.n{{fill:{DIM}}}
@keyframes lv{{50%{{opacity:.25}}}}
text{{font-family:{FONT};font-size:12px;white-space:pre}}
@media (prefers-reduced-motion:reduce){{.s,.ta,.tb,.tk,.live{{animation:none!important}}#slot0{{visibility:visible}}}}
"""

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" xml:space="preserve">',
           f"<style>{css}</style>",
           "<defs>",
           f'<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><rect x="11" y="11" width="2" height="2" fill="{DOT}"/></pattern>',
           f'<clipPath id="tclip"><rect x="{TICK_X}" y="{H - 34}" width="{W - TICK_X - 16}" height="34"/></clipPath>']
    out.append('<g id="frames">')
    out += [frame_group(fid, g, owner[fid], art_y) for fid, g in frames.items()]
    out.append("</g>")
    out.append("</defs>")

    # Card and Git City-style HUD
    out.append(f'<rect width="{W}" height="{H}" rx="12" fill="{BG}"/>')
    out.append(f'<rect width="{W}" height="{H}" rx="12" fill="url(#dots)"/>')
    out.append(chip(20, 20, "akita · jp"))
    out.append(chip(W - 20, 20, "2 agents live", dot=LIVE, align="right"))
    out.append(pixel_line([("takajun", CREAM), ("02", CLAY)], W / 2, 62, 6, track=2))
    out.append(pixel_line([("ai agent architect · software engineer", CREAM)], W / 2, 114, 2))
    out.append(pixel_line([("pair-programming with ", MUTED), ("claude code", CLAY), (" + ", MUTED), ("codex", CODEX_BASE)], W / 2, 136, 2))

    # Ghostty-style window: hairline border, traffic lights, centred title
    out.append(f'<rect x="{win_x + 4}" y="{win_y + 4}" width="{win_w}" height="{win_h:.0f}" rx="10" fill="#000" opacity=".45"/>')
    out.append(f'<rect x="{win_x}" y="{win_y}" width="{win_w}" height="{win_h:.0f}" rx="10" fill="{WINDOW}" stroke="{BORDER}"/>')
    for i, c in enumerate(("#FF605C", "#FFBD44", "#00CA4E")):
        out.append(f'<circle cx="{win_x + 18 + i * 20}" cy="{win_y + 17}" r="6" fill="{c}"/>')
    ty = win_y + 21
    tfont = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:12.5px;white-space:pre"
    out.append(f'<text class="ta" x="{W / 2}" y="{ty}" text-anchor="middle" style="{tfont}" fill="#9C9A92"><tspan fill="{CLAY}">✻</tspan> claude</text>')
    out.append(f'<text class="tb" x="{W / 2}" y="{ty}" text-anchor="middle" style="{tfont}" fill="#9C9A92"><tspan fill="{CODEX_BASE}">&gt;_</tspan> codex</text>')

    # The animation timeline (a <use> ignores transforms on the <defs> side, so offset here)
    out.append(f'<g transform="translate({art_x} 0)">')
    for i, fid in enumerate(timeline):
        out.append(f'<use id="slot{i}" class="s" href="#{fid}" style="animation-delay:{i * TICK:.2f}s"/>')
    out.append("</g>")

    # Git City-style activity ticker
    bar_y = H - 34
    out.append(f'<path d="M0 {bar_y}H{W}V{H - 12}a12 12 0 0 1 -12 12H12a12 12 0 0 1 -12 -12z" fill="#0F0F0E"/>')
    out.append(f'<path d="M0 {bar_y}.5H{W}" stroke="{BORDER}"/>')
    out.append(f'<rect class="live" x="20" y="{bar_y + 14}" width="6" height="6" fill="{LIVE}"/>')
    out.append(pixel_text("agent activity", 34, bar_y + 12, 2, CREAM)[0])
    line = pixel_text(ticker, 0, bar_y + 12, 2, MUTED)[0]
    out.append(f'<g clip-path="url(#tclip)"><g class="tk"><g transform="translate({TICK_X + 8} 0)">{line}</g><g transform="translate({TICK_X + 8 + tick_w:.0f} 0)">{line}</g></g></g>')
    out.append("</svg>")
    return "".join(out), len(frames), n, period


# === Buttons =========================================================================

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
    hero, unique, slots, period = build_hero()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "hero.svg").write_text(hero, encoding="utf-8")
    (OUT_DIR / "btn-portfolio.svg").write_text(button("portfolio >", CLAY, BG, CLAY_SHADOW), encoding="utf-8")
    (OUT_DIR / "btn-x.svg").write_text(button("x  @juntatakahashi0", WINDOW, CREAM, "#000000", border=BORDER), encoding="utf-8")
    kb = (OUT_DIR / "hero.svg").stat().st_size / 1024
    print(f"hero.svg: {unique} frames, {slots} ticks, {period:.2f}s loop, {kb:.0f} KB")


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
