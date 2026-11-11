"""The README's terminal look, shared by the hero and the Activity window.

Standard library only, so the daily Activity job can use it without numpy.

- A Ghostty-style window: hairline border, traffic lights, a centred title.
- Text in a subset of JetBrains Mono embedded as a data URI. GitHub shows
  README SVGs as images, so web fonts cannot load. The 0.6 em advance keeps
  ASCII art on its grid.
- ASCII art in ghostty.org's brightness ramp, one <text> per frame, shown for
  exactly one 31 ms tick by CSS (step-end).
- Claude Code's spinner (· ✢ ✳ ✶ ✻ ✽) and its shimmer.
"""

from __future__ import annotations

import base64
import math
from pathlib import Path
from xml.sax.saxutils import escape

FONT_FILE = Path(__file__).resolve().parent / "fonts" / "JetBrainsMono-Regular-subset.woff2"
# The subset holds printable ASCII plus these. To add a character, subset
# JetBrains Mono again with fontTools' pyftsubset and add it here.
FONT_CHARS = {chr(c) for c in range(0x20, 0x7F)} | set("·…•")
FONT_STACK = "J,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

RAMP = "·~ox+=*%$@"            # ghostty.org's brightness ramp, as in build_tj02.py
TICK = 0.031                   # s a frame, as on ghostty.org

# --- Palette: ghostty.org's greys, Claude Code's clay, Codex's blue -----------------
BG = "#0F0F11"
BORDER = "#4C4C50"
TEXT = "#C3C3C4"
MUTED = "#828286"
WHITE = "#FFFFFF"
CLAUDE, CLAUDE_SHIMMER = "#D77757", "#EB9F7F"   # Claude Code: claude / claudeShimmer
CODEX = "#63A8F8"
CREAM = "#E8E6DE"              # this profile's own cream
TRAFFIC = ("#FF605C", "#FFBD44", "#00CA4E")

# Outside a window, on GitHub's own page colour: ink and accent for each of
# its themes. The dark pair is the window's own.
PAGE = {
    "dark": {"ink": CREAM, "accent": CLAUDE, "codex": CODEX, "outline": TEXT},
    "light": {"ink": "#1F1E1D", "accent": "#C8643F", "codex": "#2F7DDB", "outline": "#66666B"},
}


def fmt(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def font_css():
    data = base64.b64encode(FONT_FILE.read_bytes()).decode()
    return (f'@font-face{{font-family:J;src:url(data:font/woff2;base64,{data}) format("woff2")}}'
            f"text{{font-family:{FONT_STACK};white-space:pre}}")


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
ASTERISK = SPINNER[4]          # ✻, Claude Code's mark


def mark(x, y, scale, fill=CLAUDE):
    """A still ✻ centred on (x, y)."""
    return f'<path transform="translate({fmt(x)} {fmt(y)}) scale({fmt(scale)})" fill="{fill}" d="{ASTERISK}"/>'


# === The two characters, flat ================================================================
# Clawd and the Codex mark from the front, at badge size, where ASCII art
# cannot be read. The measurements are the hero's models' own
# (scripts/build_agents.py: Clawd.parts, Clawd.eyes, Codex.sdf), in model units.

CLAWD_W, CLAWD_H = 17, 10
CODEX_D = 2 * (7.25 + 0.665)


def clawd_flat(x, y, u, fill):
    """Clawd with its top-left corner at (x, y), `u` px a model unit. The eyes are holes."""
    def box(bx, by, w, h):
        return f"M{fmt(x + bx * u)} {fmt(y + by * u)}h{fmt(w * u)}v{fmt(h * u)}h{fmt(-w * u)}z"
    d = (box(2, 0, 13, 8) + box(0, 4, 2, 2) + box(15, 4, 2, 2)              # body, arms
         + "".join(box(lx, 8, 1, 2) for lx in (2, 4, 12, 14))               # legs
         + box(4, 2, 1, 2) + box(12, 2, 1, 2))                              # eyes
    return f'<path fill="{fill}" fill-rule="evenodd" d="{d}"/>'


def codex_flat(cx, cy, u, stroke):
    """The Codex mark centred on (cx, cy): its ring, `>` and `_`."""
    return (f'<g transform="translate({fmt(cx)} {fmt(cy)}) scale({fmt(u)})" fill="none" stroke="{stroke}" '
            'stroke-width="1.33" stroke-linecap="round" stroke-linejoin="round"><circle r="7.25"/>'
            '<path d="M-2.917 -2.083L-1.77 0L-2.917 2.083M.833 2.083H3.333"/></g>')


# === Window ================================================================================

def window(w, h, title):
    """Ghostty's frame: hairline border, traffic lights and the title, centred."""
    out = [f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>']
    for i, c in enumerate(TRAFFIC):
        out.append(f'<circle cx="{20 + i * 20}" cy="19" r="6" fill="{c}"/>')
    tx = w / 2 - (len(title) + 2) * 13 * 0.6 / 2
    out.append(f'<path transform="translate({fmt(tx + 4)} 18.5) scale(0.62)" fill="{CLAUDE}" d="{ASTERISK}"/>')
    out.append(text(tx + 2 * 13 * 0.6, 23, title, 13, MUTED))
    return "".join(out)


# === ASCII art =============================================================================

def crop(frames):
    """Cut a loop down to the box that every frame fits in."""
    grids = [f.split("\n") for f in frames]
    used = [(r, row) for g in grids for r, row in enumerate(g) if row.strip()]
    top, bottom = min(r for r, _ in used), max(r for r, _ in used)
    left = min(len(row) - len(row.lstrip()) for _, row in used)
    right = max(len(row) for _, row in used)
    return [[row[left:] for row in g[top:bottom + 1]] for g in grids], right - left, bottom - top + 1


# Frames are laid out at 10 px and scaled down to the art's size, so every
# column lands on a whole number (0.6 em = 6 units) and the file stays smaller.
INNER_FONT = 10
INNER_CW, INNER_CH, INNER_BASE = 6, 13.2, 10.2


def layer(rows, cells):
    """One colour of a frame: a tspan per stretch of each row. Gaps shorter
    than a tspan's markup stay as spaces; the font is monospace.
    `cells` lists the frame's codes for RAMP[0], RAMP[1], ..."""
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


def frame_group(rows, layers, fid, cls, delay):
    """One frame: a <text> per (cells, class) colour layer."""
    texts = "".join(f'<text class="{c}">{layer(rows, cells)}</text>' for cells, c in layers)
    idattr = f'id="{fid}" ' if fid else ""
    return f'<g {idattr}class="{cls}" style="animation-delay:{delay:.3f}s">{texts}</g>'


def frames_css(cls, n, tick=TICK):
    """Show each frame of an n-frame loop for one tick."""
    return (f".{cls}{{visibility:hidden;animation:{cls} {n * tick:.3f}s step-end infinite}}"
            f"@keyframes {cls}{{0%{{visibility:visible}}{100 / n:.4f}%{{visibility:hidden}}}}")


# === Text ==================================================================================

def text(x, y, s, size, fill, anchor=None, extra="", check=True):
    if check:
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


def spinner(cx, cy, scale, fill, step=0.12, prefix="sp"):
    """Claude Code's spinner, forwards then backwards, one glyph per `step` seconds."""
    out = [f'<g transform="translate({fmt(cx)} {fmt(cy)}) scale({fmt(scale)})" fill="{fill}">']
    seq = list(range(len(SPINNER))) + list(reversed(range(len(SPINNER))))
    for k, g in enumerate(seq):
        out.append(f'<path id="{prefix}{k}" class="{prefix}" d="{SPINNER[g]}" style="animation-delay:{k * step:.2f}s"/>')
    out.append("</g>")
    css = (f".{prefix}{{visibility:hidden;animation:{prefix} {len(seq) * step:.2f}s step-end infinite}}"
           f"@keyframes {prefix}{{0%{{visibility:visible}}{100 / len(seq):.4f}%{{visibility:hidden}}}}")
    return "".join(out), css
