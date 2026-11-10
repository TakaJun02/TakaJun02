#!/usr/bin/env python3
"""Generate the README's sections around the hero, in the hero's look.

    python3 scripts/build_sections.py

Writes, into assets/ (standard library only):

- prompt.svg        Claude Code's input box, under the hero. It types what I
                    build, with one typo it backspaces over, then deletes.
- about.svg         One Ghostty-style window in two panes.
                    About: a Claude Code session answers /about; the fourth
                    fact is the work in progress, so it is the status line
                    with its todo list. Beside it, Japan in ASCII, in
                    ghostty.org's brightness ramp, with Akita in clay, the
                    spinner next to its name and a ping spreading over the sea.
                    Tech stack: a Codex-style session box, one row a group.
                    Claude's tools are in clay and OpenAI's in blue, as the
                    hero colours Clawd and the Codex mark.
- prompt-slash.svg  The same input box with a `/` typed, above the commands.
- cmd-*.svg         Connect as Claude Code's slash-command menu: one row a
                    link, each its own image so each can carry its own link.

Everything is drawn from scripts/terminal.py: the window, the palette, the
embedded JetBrains Mono, the ASCII grid, the spinner and the shimmer.
The session plays once and stays; only the spinner, the shimmers, the ping
and the cursors keep moving. With prefers-reduced-motion everything is still
and complete.

The coastline in scripts/data/japan.json is Natural Earth's 1:50m countries
(public domain), through world-atlas.
"""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path
from xml.sax.saxutils import escape

from terminal import (BG, BORDER, CLAUDE, CLAUDE_SHIMMER, CODEX, CREAM, GREEN, INNER_FONT, MUTED, RAMP,
                      TEXT, TICK, WHITE, fmt, font_css, frame_group, frames_css, layer, shimmer, spans,
                      spinner, text, window)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"
COAST = Path(__file__).resolve().parent / "data" / "japan.json"

W = 1000
X0 = 24                        # left edge of every pane's text, as in the Activity window
FONT_NOTE = ("<!-- Text is set in a subset of JetBrains Mono, Copyright 2020 The JetBrains Mono Project Authors,\n"
             "     SIL Open Font License 1.1. -->")
STILL = "@media (prefers-reduced-motion:reduce){*{animation:none!important}"


def svg_open(w, h, title, desc):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'xml:space="preserve" role="img" aria-labelledby="title desc">'
            f'<title id="title">{escape(title)}</title><desc id="desc">{escape(desc)}</desc>')


# === The input box =========================================================================

# One entry per phrase: the line is typed or backspaced from one target to the
# next, and the last target is what the phrase finally reads.
SCRIPTS = [
    ["Building AI Agnets", "Building AI Ag", "Building AI Agents with LLMs"],
    ["Engineering RAG Systems"],
    ["Turning AI into Practical Solutions"],
    ["Convincing my agent the task is done"],
]
PHRASES = [script[-1] for script in SCRIPTS]

BOX_H = 60
BOX_FONT = 18.0
BOX_CW = BOX_FONT * 0.6
BOX_X = 26                     # the `>`
BOX_TEXT_X = BOX_X + 2 * BOX_CW
BOX_BASE = 37.0

# Timing (seconds).
PAUSE_BEFORE = 0.6
HOLD = 1.9
TYPE_MIN, TYPE_MAX = 0.055, 0.105
TYPE_AFTER_SPACE = 0.04
NOTICE_TYPO = 0.45
BACKSPACE = 0.07
DELETE = 0.028
BLINK = 0.53


def sources(script):
    """Targets that are not just a prefix of another target: one text layer each."""
    return [t for t in script if not any(o != t and o.startswith(t) for o in script)]


def timeline():
    """Frames of (time, script index, visible text, cursor visible)."""
    rng = random.Random(2)     # fixed seed: the same "human" rhythm on every build
    frames = []
    t = 0.0

    def idle(duration, i, line, blink=True):
        nonlocal t
        end, on = t + duration, True
        while t < end - 1e-9:
            frames.append((t, i, line, on))
            t = min(t + (BLINK if blink else duration), end)
            on = not on

    for i, script in enumerate(SCRIPTS):
        idle(PAUSE_BEFORE, i, "")
        line = ""
        for target in script:
            keep = os.path.commonprefix([line, target])
            if len(line) > len(keep):      # spotted a typo: pause, then backspace
                idle(NOTICE_TYPO, i, line, blink=False)
                for k in range(len(line) - 1, len(keep) - 1, -1):
                    frames.append((t, i, line[:k], True))
                    t += BACKSPACE
                line = keep
            for k in range(len(line) + 1, len(target) + 1):
                frames.append((t, i, target[:k], True))
                t += rng.uniform(TYPE_MIN, TYPE_MAX)
                if target[k - 1] == " ":
                    t += TYPE_AFTER_SPACE
            line = target
        idle(HOLD, i, line)
        for k in range(len(line) - 1, -1, -1):
            frames.append((t, i, line[:k], True))
            t += DELETE
    return frames, t


def discrete(attr, samples, dur):
    """A discrete SMIL <animate>, dropping samples that repeat the previous value."""
    kept = []
    for t, v in samples:
        if not kept or kept[-1][1] != v:
            kept.append((t, v))
    kept.append((dur, kept[-1][1]))
    values = ";".join(v for _, v in kept)
    key_times = ";".join(f"{t / dur:.4f}" for t, _ in kept)
    return (f'<animate attributeName="{attr}" values="{values}" keyTimes="{key_times}" '
            f'calcMode="discrete" dur="{dur:.3f}s" repeatCount="indefinite"/>')


def box_frame(h=BOX_H):
    """Claude Code's input box: the window's hairline and corner, and the prompt."""
    return (f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>'
            + text(BOX_X, BOX_BASE, ">", BOX_FONT, MUTED))


def cursor_rect(x, extra=""):
    return (f'<rect x="{fmt(x)}" y="{fmt(BOX_BASE - BOX_FONT * 0.82)}" width="{fmt(BOX_CW - 1.5)}" '
            f'height="{fmt(BOX_FONT * 1.1)}" fill="{TEXT}"{extra}')


def build_prompt():
    """The input box, typing each phrase in turn. Every distinct line sits under
    a clipPath whose width steps one cell at a time (SMIL, discrete)."""
    frames, dur = timeline()
    layers = [(i, src) for i, script in enumerate(SCRIPTS) for src in sources(script)]

    def layer_of(i, visible):
        return next(n for n, (j, src) in enumerate(layers) if j == i and src.startswith(visible))

    active = [(t, layer_of(i, v), len(v), on) for t, i, v, on in frames]
    clips, groups = [], []
    for n, (_, src) in enumerate(layers):
        widths = [(t, fmt(k * BOX_CW if lay == n else 0)) for t, lay, k, _ in active]
        clips.append(f'<clipPath id="t{n}"><rect x="{fmt(BOX_TEXT_X)}" y="0" width="0" height="{BOX_H}">'
                     f'{discrete("width", widths, dur)}</rect></clipPath>')
        groups.append(f'<g clip-path="url(#t{n})">{text(BOX_TEXT_X, BOX_BASE, src, BOX_FONT, WHITE)}</g>')
    cursor = (cursor_rect(BOX_TEXT_X) + ">"
              + discrete("x", [(t, fmt(BOX_TEXT_X + k * BOX_CW)) for t, _, k, _ in active], dur)
              + discrete("opacity", [(t, "1" if on else "0") for t, _, _, on in active], dur) + "</rect>")
    still = PHRASES[0]
    static = (f'<g class="still">{text(BOX_TEXT_X, BOX_BASE, still, BOX_FONT, WHITE)}'
              f'{cursor_rect(BOX_TEXT_X + len(still) * BOX_CW)}/></g>')
    css = (font_css() + ".still{display:none}"
           "@media (prefers-reduced-motion:reduce){.motion{display:none}.still{display:inline}}")
    return (svg_open(W, BOX_H, "What I build", "A Claude Code input box types, then deletes: " + "; ".join(PHRASES) + ".")
            + FONT_NOTE + f"<defs>{''.join(clips)}</defs><style>{css}</style>" + box_frame()
            + f'<g class="motion">{"".join(groups)}{cursor}</g>' + static + "</svg>")


def build_prompt_slash():
    """The input box with `/` typed: what opens the command menu under it."""
    css = (font_css() + f".cu{{animation:cu {2 * BLINK:.2f}s step-end infinite}}"
           "@keyframes cu{50%{opacity:0}}" + STILL + "}")
    return (svg_open(W, BOX_H, "Connect", "A Claude Code input box with a slash typed, opening the command menu below.")
            + FONT_NOTE + f"<style>{css}</style>" + box_frame()
            + text(BOX_TEXT_X, BOX_BASE, "/", BOX_FONT, WHITE)
            + cursor_rect(BOX_TEXT_X + BOX_CW, ' class="cu"') + "/></svg>")


# === The command menu ======================================================================

CMD_H = 56
CMD_FONT = BOX_FONT            # the menu sits on the input box's grid
CMD_CW = CMD_FONT * 0.6
COMMANDS = [                   # (file, command, where it goes); the first is the selected row
    ("portfolio", "/portfolio", "takajun02.com"),
    ("x", "/x", "@JuntaTakahashi0"),
    ("github", "/github", "TakaJun02"),
]


def build_command(command, target, selected):
    """One row of the slash-command menu. The selected row is in clay, as
    Claude Code colours its selection, and shimmers."""
    y = 35.0
    name_x, target_x = BOX_TEXT_X, BOX_TEXT_X + 14 * CMD_CW
    css = [font_css()]
    out = [f'<rect x=".5" y=".5" width="{W - 1}" height="{CMD_H - 1}" rx="8" fill="{BG}" '
           f'stroke="{CLAUDE if selected else BORDER}"/>']
    if selected:
        word, word_css = shimmer("s", name_x, y, command, CMD_FONT, CLAUDE, CLAUDE_SHIMMER, 3.2)
        out.append(word)
        css.append(word_css)
        css.append(STILL + "}")
    else:
        out.append(text(name_x, y, command, CMD_FONT, TEXT))
    out.append(text(target_x, y, target, CMD_FONT, TEXT if selected else MUTED))
    return (svg_open(W, CMD_H, command, f"{command}: {target}") + FONT_NOTE
            + f"<style>{''.join(css)}</style>" + "".join(out) + "</svg>")


# === About: the map ========================================================================

ART = 8.0                      # px, the ASCII pictures, as in the hero
ART_CW, ART_CH = ART * 0.6, ART * 1.32
MAP_ROWS = 32
LON0, LON1, LAT0, LAT1 = 128.6, 146.2, 30.8, 45.8      # Kyushu to Hokkaido: the four main islands
KX = math.cos(math.radians(38))                        # a degree of longitude, in degrees of latitude
AKITA_BOX = (139.7, 140.95, 38.9, 40.45)               # the prefecture, near enough at 25 km a cell
AKITA = (140.1, 39.7)
PING_FRAMES, PING_RUN, PING_REACH = 129, 80, 130.0     # a 4 s loop, as the radar's sweep; the ring spreads for 2.5 s
LABEL_REACH = 96                                       # px the name and its leader take, west of Akita


def inside(px, py, poly):
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def japan():
    """Japan as cells: (land rows, Akita rows, ping frames, cols, Akita's centre in px).
    A cell's glyph follows how much of it is land, so the coast fades out."""
    k = MAP_ROWS * ART_CH / (LAT1 - LAT0)              # px a degree of latitude

    def px(lon, lat):
        return (lon - LON0) * KX * k, (LAT1 - lat) * k

    cols = math.ceil(px(LON1, LAT0)[0] / ART_CW)
    polys = [[px(lon, lat) for lon, lat in ring] for ring in json.loads(COAST.read_text())]
    boxes = [(min(x for x, _ in p), max(x for x, _ in p), min(y for _, y in p), max(y for _, y in p)) for p in polys]

    def is_land(x, y):
        return any(b[0] <= x <= b[1] and b[2] <= y <= b[3] and inside(x, y, p) for p, b in zip(polys, boxes))

    (ax0, ay1), (ax1, ay0) = px(AKITA_BOX[0], AKITA_BOX[2]), px(AKITA_BOX[1], AKITA_BOX[3])
    land = [[" "] * cols for _ in range(MAP_ROWS)]
    akita = [[" "] * cols for _ in range(MAP_ROWS)]
    for r in range(MAP_ROWS):
        for c in range(cols):
            hits = sum(is_land((c + (i + 0.5) / 3) * ART_CW, (r + (j + 0.5) / 6) * ART_CH)
                       for i in range(3) for j in range(6))
            if hits < 2:
                continue
            glyph = RAMP[min(8, 1 + round(hits / 18 * 7))]
            cx, cy = (c + 0.5) * ART_CW, (r + 0.5) * ART_CH
            (akita if ax0 <= cx <= ax1 and ay0 <= cy <= ay1 else land)[r][c] = glyph

    # The ping: a ring spreading from Akita over the sea, fainter as it grows.
    ax, ay = px(*AKITA)
    ping = []
    for f in range(PING_FRAMES):
        g = [[" "] * cols for _ in range(MAP_ROWS)]
        if f < PING_RUN:
            p = (f + 1) / PING_RUN
            radius = PING_REACH * (1 - (1 - p) ** 1.5)         # eases out
            glyph = RAMP[2] if p < 0.3 else RAMP[1] if p < 0.6 else RAMP[0]
            for r in range(MAP_ROWS):
                for c in range(cols):
                    if land[r][c] != " " or akita[r][c] != " ":
                        continue
                    dx, dy = (c + 0.5) * ART_CW - ax, (r + 0.5) * ART_CH - ay
                    if -LABEL_REACH < dx < 0 and abs(dy) < 14:     # the name and its leader
                        continue
                    d = math.hypot(dx, dy)
                    reach = (abs(dx) * ART_CW + abs(dy) * ART_CH) / (2 * max(d, 1e-9))
                    if abs(d - radius) < reach * 0.6:
                        g[r][c] = glyph
        ping.append(["".join(row) for row in g])
    as_rows = lambda g: ["".join(row) for row in g]
    return as_rows(land), as_rows(akita), ping, cols, (ax, ay)


# === About: the window =====================================================================

UI = 15.0                      # px, the session's text
UI_CW = UI * 0.6
PITCH = 28                     # px a line
A_TOP = 38
FACTS = [                      # (text, emphasis) pieces; the emphasis is the old README's bold
    [("Graduate student at ", 0), ("Akita Prefectural University", 1)],
    [("Software engineer focused on ", 0), ("LLMs, AI agents, and RAG", 1)],
    [("Hands-on industry experience building ", 0), ("RAG-powered AI agents", 1)],
]
EXPLORING = "Exploring agent architecture…"
TODOS = ["Tool calling", "Sub-agents", "Context management", "Human-in-the-loop"]
STACK = [                      # the old README's groups and badges, in its order
    ("ai / llm", ["LangGraph", "LangChain", "Claude API", "OpenAI API", "Ollama", "vLLM", "RAG"]),
    ("languages", ["Python", "TypeScript", "JavaScript"]),
    ("backend / frontend", ["FastAPI", "Vue.js"]),
    ("databases", ["PostgreSQL", "SQLite", "ChromaDB", "Qdrant"]),
    ("infrastructure / tools", ["Docker", "AWS", "Git", "GitHub", "Linux", "Claude Code", "Codex"]),
]
TOOL_COLOURS = {"Claude API": CLAUDE, "Claude Code": CLAUDE, "OpenAI API": CODEX, "Codex": CODEX}

# The session, in seconds from load. It plays once and stays.
TYPE_AT, PER_KEY = 0.5, 0.09
FACT_AT, FACT_STEP, FACT_PER = 1.5, 0.42, 0.006
STATUS_AT, TODO_STEP = 3.0, 0.16
STACK_AT, STACK_STEP = 0.4, 0.12


def after(t):
    """Hidden until `t`, then there for good."""
    return f' class="a" style="animation-delay:{t:.2f}s"'


def typed(x, y, pieces, size, start, per):
    """Coloured pieces revealed one cell at a time, by a cover that shrinks away."""
    n = sum(len(s) for s, _ in pieces)
    width = n * size * 0.6
    return (spans(x, y, pieces, size)
            + f'<rect class="ty" x="{fmt(x - 1)}" y="{fmt(y - size)}" width="{fmt(width + 1)}" height="{fmt(size * 1.45)}" '
            f'fill="{BG}" style="animation:ty {n * per:.2f}s steps({n},end) {start:.2f}s both"/>')


def about_pane(top):
    out, css = [], []
    y = [top + 44 + PITCH * i for i in range(12)]

    # > /about, typed with a moving cursor, then submitted.
    cmd = "/about"
    end = TYPE_AT + len(cmd) * PER_KEY
    out += [text(X0, y[0], ">", UI, MUTED),
            typed(X0 + 2 * UI_CW, y[0], [(cmd, WHITE)], UI, TYPE_AT, PER_KEY),
            f'<rect class="cur" x="{fmt(X0 + 2 * UI_CW)}" y="{fmt(y[0] - UI * 0.82)}" width="{fmt(UI_CW)}" '
            f'height="{fmt(UI * 1.1)}" fill="{TEXT}"/>']
    hide = end + 0.3
    css.append(f".cur{{opacity:0;animation:cur {hide:.2f}s linear both}}"
               f"@keyframes cur{{0%,{TYPE_AT / hide * 100:.2f}%{{opacity:1;transform:translateX(0);"
               f"animation-timing-function:steps({len(cmd)},end)}}"
               f"{end / hide * 100:.2f}%,99.9%{{opacity:1;transform:translateX({fmt(len(cmd) * UI_CW)}px)}}"
               f"100%{{opacity:0;transform:translateX({fmt(len(cmd) * UI_CW)}px)}}}}")

    # The three facts, each a line of Claude Code's reply.
    for i, pieces in enumerate(FACTS):
        t = FACT_AT + i * FACT_STEP
        yy = y[2 + i] - 10
        out.append(f'<circle cx="{X0 + 5}" cy="{fmt(yy + 10 - UI * 0.33)}" r="4.5" fill="{CREAM}"{after(t)}/>')
        out.append(typed(X0 + 2 * UI_CW, yy + 10, [(s, WHITE if strong else TEXT) for s, strong in pieces],
                         UI, t, FACT_PER))

    # The fourth is still under way: the status line, with its todo list under it.
    row = 6
    sp, sp_css = spinner(X0 + UI_CW / 2, y[row] - UI * 0.36, 0.78, CLAUDE)
    word, word_css = shimmer("s1", X0 + 2 * UI_CW, y[row], EXPLORING, UI, CLAUDE, CLAUDE_SHIMMER, 3.0)
    css += [sp_css, word_css]
    out.append(f"<g{after(STATUS_AT)}>{sp}{word}"
               + text(X0 + (2 + len(EXPLORING)) * UI_CW, y[row], " (esc to interrupt)", UI, MUTED) + "</g>")
    tx = X0 + 5 * UI_CW
    out.append(f'<path d="M{fmt(X0 + 2 * UI_CW + 2)} {y[row + 1] - 17}V{y[row + 1] - 5}H{fmt(X0 + 4 * UI_CW)}" '
               f'stroke="{MUTED}" stroke-width="1.2" fill="none"{after(STATUS_AT + 0.2)}/>')
    for i, todo in enumerate(TODOS):
        yy = y[row + 1 + i]
        out.append(f"<g{after(STATUS_AT + 0.2 + i * TODO_STEP)}>"
                   f'<rect x="{fmt(tx + 0.5)}" y="{fmt(yy - 10.5)}" width="10" height="10" fill="none" stroke="{MUTED}" stroke-width="1.2"/>'
                   + text(tx + 2 * UI_CW, yy, todo, UI, TEXT) + "</g>")

    # Japan, with Akita in clay.
    land, akita, ping, cols, (ax, ay) = japan()
    map_w, map_h = cols * ART_CW, MAP_ROWS * ART_CH
    mx, my = W - X0 - 8 - map_w, top + 22
    frames = "".join(frame_group(rows, [(RAMP, "mp")], "pg0" if i == 0 else None, "pg", i * TICK)
                     for i, rows in enumerate(ping) if i == 0 or any(row.strip() for row in rows))
    out.append(f'<g transform="translate({fmt(mx)} {fmt(my)}) scale({fmt(ART / INNER_FONT)})" font-size="{INNER_FONT}">'
               f'<text class="ml">{layer(land, RAMP)}</text><text class="ma">{layer(akita, RAMP)}</text>{frames}</g>')
    css.append(frames_css("pg", PING_FRAMES) + f".ml{{fill:{MUTED}}}.ma{{fill:{CLAUDE}}}.mp{{fill:{CLAUDE};opacity:.6}}")
    # Its name, out in the Sea of Japan, with the spinner turning beside it.
    label = "Akita"
    lx = mx + ax - LABEL_REACH + 26
    ly = my + ay + 4
    sp2, sp2_css = spinner(lx - 10, ly - 12 * 0.36, 0.62, CLAUDE, prefix="sq")
    css.append(sp2_css)
    out.append(sp2 + text(lx, ly, label, 12, WHITE)
               + f'<path d="M{fmt(lx + len(label) * 7.2 + 6)} {fmt(ly - 4)}H{fmt(mx + ax - 10)}" stroke="{MUTED}"/>')
    return "".join(out), "".join(css), my + map_h + 20 - top


def stack_pane(top):
    """A Codex-style session box: `>_`, a name, then one `key: values` row a group."""
    pad_x, pad_y = 2 * UI_CW, 16
    label_cols = max(len(name) for name, _ in STACK) + 3
    box_x, box_y, box_w = X0, top + 22, W - 2 * X0
    rows = len(STACK) + 2
    box_h = rows * PITCH + 2 * pad_y - 8
    tx = box_x + pad_x
    y = [box_y + pad_y + 14 + PITCH * i for i in range(rows)]
    out = [f'<rect x="{fmt(box_x + .5)}" y="{fmt(box_y + .5)}" width="{fmt(box_w - 1)}" height="{fmt(box_h - 1)}" rx="7" '
           f'fill="none" stroke="{BORDER}"/>',
           spans(tx, y[0], [(">_", CODEX), (" ", TEXT), ("Tech stack", WHITE)], UI)]
    for i, (name, tools) in enumerate(STACK):
        pieces = [(f"{name}:".ljust(label_cols), MUTED)]
        for tool in tools:
            pieces += [(tool, TOOL_COLOURS.get(tool, TEXT)), ("   ", TEXT)]
        out.append(f"<g{after(STACK_AT + i * STACK_STEP)}>{spans(tx, y[2 + i], pieces[:-1], UI)}</g>")
    return "".join(out), box_y + box_h + 24 - top


def build_about():
    a, a_css, a_h = about_pane(A_TOP)
    b_top = A_TOP + a_h
    b, b_h = stack_pane(b_top)
    H = round(b_top + b_h)
    facts = ". ".join("".join(s for s, _ in pieces) for pieces in FACTS)
    desc = (f"About: {facts}. {EXPLORING[:-1]}: {', '.join(t.lower() for t in TODOS)}. "
            "A map of Japan in ASCII marks Akita. Tech stack: "
            + "; ".join(f"{name}: {', '.join(tools)}" for name, tools in STACK) + ".")
    css = [font_css(), a_css,
           ".a{opacity:0;animation:a .01s linear both}@keyframes a{from{opacity:0}to{opacity:1}}"
           ".ty{transform:scaleX(0);transform-box:fill-box;transform-origin:right}"
           "@keyframes ty{from{transform:scaleX(1)}to{transform:scaleX(0)}}",
           STILL + ".a{opacity:1}.ty{transform:scaleX(0)}#sp8,#sq8,#pg0{visibility:visible}}"]
    return (svg_open(W, H, "About TakaJun02", desc)
            + "<!-- Generated by scripts/build_sections.py. The coastline is Natural Earth's (public domain).\n"
            "     Text is set in a subset of JetBrains Mono, Copyright 2020 The JetBrains Mono Project Authors,\n"
            "     SIL Open Font License 1.1. -->"
            + f"<style>{''.join(css)}</style>" + window(W, H, "about")
            + f'<path d="M1 {fmt(b_top)}H{W - 1}" stroke="{BORDER}"/>' + a + b + "</svg>"), H


def main():
    OUT_DIR.mkdir(exist_ok=True)
    about, h = build_about()
    files = {"about.svg": about, "prompt.svg": build_prompt(), "prompt-slash.svg": build_prompt_slash()}
    for i, (name, command, target) in enumerate(COMMANDS):
        files[f"cmd-{name}.svg"] = build_command(command, target, selected=i == 0)
    for name, svg in files.items():
        (OUT_DIR / name).write_text(svg, encoding="utf-8")
        print(f"{name}: {len(svg) / 1024:.0f} KB" + (f", {W}x{h}" if name == "about.svg" else ""))


if __name__ == "__main__":
    main()
