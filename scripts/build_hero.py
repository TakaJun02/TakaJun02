#!/usr/bin/env python3
"""Generate the hero image at the top of README.md and the two buttons under it.

    python3 scripts/build_hero.py

Writes assets/hero.svg, assets/btn-portfolio.svg and assets/btn-x.svg.
Needs numpy. Only this script uses it, and the CI workflow never runs it,
because the hero does not depend on activity data.

What it draws
- A Ghostty-style terminal window (after ghostty.org). Inside it, Clawd from
  Claude Code and the Codex mark take turns floating, drawn as ASCII the way
  ghostty.org draws its ghost: one ray per character cell, shading mapped onto
  the 10-step ramp from ghostty-org/website's
  bin/video-to-terminal/video-to-terminal.sh (MIT), and a second-colour aura a
  few cells outside the silhouette.
- Around it, Git City's UI language (after thegitcity.com): Silkscreen pixel
  type drawn as paths, dark panels, hard offset shadows, HUD chips and an
  activity ticker. GitHub shows README SVGs as images, so web fonts never load;
  GLYPHS below holds Silkscreen's bitmaps at its native 8px size (OFL-1.1).
- Clawd follows the quadrant-pixel layout that Claude Code prints. The Codex
  mark uses the path in openai/codex codex-rs/tui/src/empty_state_animation/
  paths.rs. Both are fan art of other people's characters. The README says so
  under the image.

How it moves
- Like the Ghostty ghost, each character idles instead of spinning: it sways
  left and right, bobs, and breathes (squash and stretch). On top of that the
  shapes are soft: Clawd's top lags behind the sway like jelly, its legs
  paddle and its arms wave; the Codex ring ripples and the `>_` drifts inside
  it. Clawd blinks, and the Codex cursor blinks.
- The aura is re-traced from every frame's silhouette, and its characters ripple
  around the outline.
- The whole art group also floats on a slow CSS ease, which runs at the
  display's frame rate, so the motion stays smooth between ASCII frames.

How it animates
- One idle loop is LOOP frames, and every phase term is a whole multiple of the
  loop, so it repeats seamlessly. Each distinct frame is a <g> in <defs>; the
  timeline is a row of <use> slots, one per TICK, and CSS shows each slot for
  exactly one tick (step-end). Repeating a loop reuses its frames.
- The two characters swap through a short dissolve.
- Every glyph in a monospace font has the same advance, so the rows stay
  aligned in whichever monospace font the viewer has.
- prefers-reduced-motion shows Clawd's first frame and stops the ticker and
  the float.
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
AURA = "#B0AEA5"
CLAWD_BASE = "#D77757"   # Claude Code's `claude` colour
CODEX_BASE = "#63A8F8"   # Codex's UI accent

# --- ASCII renderer --------------------------------------------------------------
RAMP = "·~ox+=*%$@"    # ghostty.org's ramp, darkest to brightest
COLS, ROWS = 76, 30
CELL_W, CELL_H = 7.2, 13.0
ASPECT = CELL_H / CELL_W
FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
LIGHT_POS = np.array([-14.0, 13.0, -22.0])   # a point light up and to the left of the camera
AURA_GAP, AURA_WIDTH = 2.6, 1.8              # in column widths, measured from the silhouette

# --- Timeline -----------------------------------------------------------------------
TICK = 0.07            # seconds per frame
LOOP = 36              # frames in one idle loop (2.52 s)
REPEAT = 2             # idle loops per character before they swap
DISSOLVE = 4
FLOAT_PERIOD = 2 * LOOP * TICK
FLOAT_PX = 6


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
    scale = 0.32            # world units per column
    sway, bob = 0.44, 0.9   # radians, world units

    def __init__(self, phase=0.0, blink=False):
        d = self.depth / 2
        self.sy = 1 + 0.05 * math.sin(2 * phase)          # breathe twice per loop
        self.sxz = 1 / math.sqrt(self.sy)
        self.lean = 0.7 * math.sin(phase - 0.8)           # the top lags behind the sway
        arm = 0.6 * math.sin(2 * phase)
        self.parts = [
            ((0, 1, 0), (6.5, 4, d)),            # body: pixel rows 0-3, columns 3-15
            ((-7.5, arm, 0), (1, 1, 1.5)),       # arms: row 2, columns 1-2 and 16-17
            ((7.5, -arm, 0), (1, 1, 1.5)),
        ]
        for k, x in enumerate((-6, -4, 4, 6)):   # legs: row 4, columns 3, 5, 13, 15
            for j, z in enumerate((-d + 0.5, d - 0.5)):
                a = 2 * phase + k * math.pi / 2 + j * math.pi
                self.parts.append(((x, -4 + 0.35 * max(0.0, math.sin(a)), z + 0.45 * math.cos(a)), (0.5, 1, 0.5)))
        # Eyes are sockets carved into the front face (row 1, columns 5 and 13).
        # A closed eye leaves only a thin slit at the bottom, like Claude Code's `▂`.
        eye_y, eye_h = ((1.25, 0.25) if blink else (2.0, 1.0))
        self.eyes = [((x, eye_y, -d), (0.5, eye_h, 0.6)) for x in (-4, 4)]

    def warp(self, p):
        x, y, z = p[:, 0] / self.sxz, p[:, 1] / self.sy, p[:, 2] / self.sxz
        k = np.clip((y + 5) / 10, 0.0, 1.0)
        return np.stack([x - self.lean * k * k, y, z], axis=1)

    def sdf(self, p):
        q = self.warp(p)
        body = np.min([sd_box(q, c, h) for c, h in self.parts], axis=0)
        eyes = np.min([sd_box(q, c, h, r=0.02) for c, h in self.eyes], axis=0)
        return np.maximum(body, -eyes) * min(self.sy, self.sxz)

    def material(self, p):
        q = self.warp(p)
        eyes = np.min([sd_box(q, c, h, r=0.02) for c, h in self.eyes], axis=0)
        return np.where(eyes < 0.08, "eye", "body")


class CodexMark:
    """The Codex mark (ring, `>` and `_`) extruded into a thick coin."""

    depth = 2.2
    scale = 0.38
    sway, bob = 0.5, 0.8
    half_stroke = 0.665

    def __init__(self, phase=0.0, cursor=True):
        self.phase = phase
        self.cursor = cursor
        self.sy = 1 + 0.045 * math.sin(2 * phase)
        self.sxz = 1 / math.sqrt(self.sy)
        self.drift = (0.28 * math.sin(2 * phase + 1.1), 0.24 * math.sin(2 * phase + 2.3))

    def sdf(self, p):
        x, y, z = p[:, 0] / self.sxz, p[:, 1] / self.sy, p[:, 2] / self.sxz
        # paths.rs works in a 20x20 box with y pointing down; centre it, y up.
        X, Y = x + 10.0, 10.0 - y
        ang = np.arctan2(Y - 10.0, X - 10.0)
        ripple = 0.32 * np.sin(3 * ang - 2 * self.phase) + 0.14 * np.sin(5 * ang + self.phase)
        hs = self.half_stroke
        ring = np.abs(np.hypot(X - 10.0, Y - 10.0) - (7.25 + ripple)) - hs
        gx, gy = X - self.drift[0], Y - self.drift[1]
        shape = np.minimum(ring, np.minimum(sd_segment2(gx, gy, (7.083, 7.917), (8.23, 10.0)),
                                            sd_segment2(gx, gy, (8.23, 10.0), (7.083, 12.083))) - hs)
        if self.cursor:
            shape = np.minimum(shape, sd_segment2(gx, gy, (10.833, 12.083), (13.333, 12.083)) - hs)
        wz = np.abs(z) - self.depth / 2
        w = np.stack([shape, wz], axis=1)
        d = np.minimum(w.max(axis=1), 0.0) + np.linalg.norm(np.maximum(w, 0.0), axis=1)
        return d * min(self.sy, self.sxz)

    def material(self, p):
        return np.full(len(p), "body", dtype=object)


def rotation(yaw, tilt):
    cy, sy, ct, st = math.cos(yaw), math.sin(yaw), math.cos(tilt), math.sin(tilt)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])
    return rx @ ry


def render(model, yaw, tilt, lift):
    """Ray-march one frame. Returns (grid, mask): grid holds (char, cls) or None."""
    s = model.scale
    cols = (np.arange(COLS) + 0.5 - COLS / 2) * s
    rows = (ROWS / 2 - np.arange(ROWS) - 0.5) * s * ASPECT
    u, v = np.meshgrid(cols, rows)
    origin = np.stack([u.ravel(), v.ravel() - lift, np.full(u.size, -30.0)], axis=1)
    rot = rotation(yaw, tilt)
    inv = rot.T
    o = origin @ inv.T
    d = np.array([0.0, 0.0, 1.0]) @ inv.T
    t = np.zeros(len(o))
    alive = np.ones(len(o), dtype=bool)
    hit = np.zeros(len(o), dtype=bool)
    for _ in range(160):
        idx = np.flatnonzero(alive)
        if not len(idx):
            break
        dist = model.sdf(o[idx] + t[idx, None] * d)
        done = dist < 2e-3
        hit[idx[done]] = True
        t[idx] += dist * 0.9                       # the warps stretch distances a little
        alive[idx[done | (t[idx] > 60)]] = False
    grid = [[None] * COLS for _ in range(ROWS)]
    mask = hit.reshape(ROWS, COLS)
    if not hit.any():
        return grid, mask
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
        grid[r][c] = (RAMP[int(lum[k] * len(RAMP))], "")
    return grid, mask


def add_aura(grid, mask, phase):
    """Ghostty's outline: a band a few cells outside the silhouette, in a second
    colour, whose characters ripple around the shape."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return grid
    gy, gx = np.mgrid[0:ROWS, 0:COLS]
    dist = np.full((ROWS, COLS), np.inf)
    for chunk in range(0, len(ys), 256):
        dy = (gy[..., None] - ys[None, None, chunk:chunk + 256]) * ASPECT
        dx = gx[..., None] - xs[None, None, chunk:chunk + 256]
        dist = np.minimum(dist, np.sqrt(dx * dx + dy * dy).min(axis=2))
    band = (dist >= AURA_GAP) & (dist < AURA_GAP + AURA_WIDTH) & ~mask
    ang = np.arctan2((gy - ys.mean()) * ASPECT, gx - xs.mean())
    wave = 0.5 + 0.5 * np.sin(6 * ang - 2 * phase) * np.cos(2 * ang + phase)
    fade = 1.0 - (dist - AURA_GAP) / AURA_WIDTH
    level = np.clip(2 + np.round(5 * wave * (0.45 + 0.55 * fade)), 1, 7).astype(int)
    for r, c in zip(*np.nonzero(band)):
        grid[r][c] = (RAMP[level[r, c]], "o")
    return grid


def idle_frames(make, sway, bob, blink_ticks=()):
    """One seamless idle loop: sway, bob and a slight nod, all whole multiples of the loop."""
    frames = []
    for k in range(LOOP):
        phase = 2 * math.pi * k / LOOP
        model = make(phase, k)
        yaw = sway * math.sin(phase)
        tilt = math.radians(-14 + 3 * math.sin(2 * phase + 0.5))
        lift = bob * math.sin(phase + 0.6)
        grid, mask = render(model, yaw, tilt, lift)
        frames.append(add_aura(grid, mask, phase))
    return frames


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

def layered_group(fid, grid, y0):
    """A dissolve frame mixes cells from both characters and noise, which would
    need a tspan almost every cell. Instead draw one layer of rows per colour:
    Clawd ("a"), Codex ("b"), aura ("o") and noise ("n")."""
    layers = {"a": [], "b": [], "o": [], "n": []}
    for r, row in enumerate(grid):
        rows = {k: [" "] * COLS for k in layers}
        for c, cell in enumerate(row):
            if not cell:
                continue
            ch, cls = cell
            key = "o" if "o" in cls.split() else ("n" if cls == "n" else cls.split()[0])
            rows[key][c] = ch
        for k, chars in rows.items():
            line = "".join(chars).rstrip()
            if line:
                layers[k].append(f'<text y="{y0 + (r + 1) * CELL_H - 3:.0f}">{escape(line)}</text>')
    body = "".join(f'<g class="{k}">{"".join(v)}</g>' for k, v in layers.items() if v)
    return f'<g id="{fid}">{body}</g>'


def frame_group(fid, grid, base, y0):
    """One frame. The group sets the body colour; tspans mark the aura ("o"),
    each character's own cells during a dissolve ("a", "b") and dissolve noise
    ("n"). Every glyph in a monospace font has the same advance, so rows stay
    aligned in any font without textLength."""
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
    clawd = idle_frames(lambda ph, k: Clawd(ph, blink=k in (26, 27)), Clawd.sway, Clawd.bob)
    codex = idle_frames(lambda ph, k: CodexMark(ph, cursor=(k % 18) < 10), CodexMark.sway, CodexMark.bob)
    frames, owner = {}, {}
    for k, g in enumerate(clawd):
        frames[f"a{k}"], owner[f"a{k}"] = g, "ca"
    for k, g in enumerate(codex):
        frames[f"b{k}"], owner[f"b{k}"] = g, "cb"
    # Dissolves keep each cell's own colour: Clawd's cells in clay, Codex's in blue.
    for i, g in enumerate(dissolve(tag(clawd[0], "a"), tag(codex[0], "b"), DISSOLVE, seed=2)):
        frames[f"ab{i}"], owner[f"ab{i}"] = g, "cm"
    for i, g in enumerate(dissolve(tag(codex[0], "b"), tag(clawd[0], "a"), DISSOLVE, seed=5)):
        frames[f"ba{i}"], owner[f"ba{i}"] = g, "cm"

    timeline = [f"a{k}" for k in range(LOOP)] * REPEAT
    timeline += [f"ab{i}" for i in range(DISSOLVE)]
    swap_to_codex = len(timeline) - DISSOLVE // 2
    timeline += [f"b{k}" for k in range(LOOP)] * REPEAT
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
.fl{{animation:fl {FLOAT_PERIOD:.2f}s ease-in-out infinite}}
@keyframes fl{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-{FLOAT_PX}px)}}}}
.tk{{animation:tk {tick_w / 40:.1f}s linear infinite}}
@keyframes tk{{to{{transform:translateX(-{tick_w:.0f}px)}}}}
.live{{animation:lv 1.6s steps(2) infinite}}
@keyframes lv{{50%{{opacity:.25}}}}
.ca,.a{{fill:{CLAWD_BASE}}}.cb,.b{{fill:{CODEX_BASE}}}.cm,.n{{fill:{DIM}}}.o{{fill:{AURA}}}
text{{font-family:{FONT};font-size:12px;white-space:pre}}
@media (prefers-reduced-motion:reduce){{.s,.ta,.tb,.fl,.tk,.live{{animation:none!important}}#slot0{{visibility:visible}}}}
"""

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" xml:space="preserve">',
           f"<style>{css}</style>",
           "<defs>",
           f'<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><rect x="11" y="11" width="2" height="2" fill="{DOT}"/></pattern>',
           f'<clipPath id="tclip"><rect x="{TICK_X}" y="{H - 34}" width="{W - TICK_X - 16}" height="34"/></clipPath>']
    out += [layered_group(fid, g, art_y) if owner[fid] == "cm" else frame_group(fid, g, owner[fid], art_y)
            for fid, g in frames.items()]
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

    # The animation timeline. A <use> ignores transforms on the <defs> side, so the
    # offset lives here, and the float sits on its own group so CSS does not
    # replace the offset.
    out.append(f'<g transform="translate({art_x} 0)"><g class="fl">')
    for i, fid in enumerate(timeline):
        out.append(f'<use id="slot{i}" class="s" href="#{fid}" style="animation-delay:{i * TICK:.2f}s"/>')
    out.append("</g></g>")

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
