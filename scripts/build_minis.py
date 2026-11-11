#!/usr/bin/env python3
"""Generate the small Clawd and Codex mark that turn up down the README.

    python3 scripts/build_minis.py

Writes assets/mini-clawd-dark.svg, mini-clawd-light.svg, mini-codex-dark.svg
and mini-codex-light.svg. Needs numpy, for the characters.

They are the hero's two characters, not drawings of them: the same models and
renderer (scripts/build_agents.py), the same loop (scripts/build_hero.py's
timelines: float, glance, blink, one turn), at a little over half the hero's
size, with the outline brought in to match. They have no window behind them,
so each comes in GitHub's two themes and README.md picks one with <picture>.
prefers-reduced-motion shows the first frame.
"""

from __future__ import annotations

from terminal import INNER_CH, INNER_CW, INNER_FONT, PAGE, TICK, crop, fmt, font_css, frame_group
from build_agents import BODY_CELLS, LINE_CELLS, render_all, simulate
from build_hero import CLAWD_TL, CODEX_TL, LOOP, OUT_DIR, SCALE

MINI = 0.42                    # of docs/agents.html's characters; the hero's are 0.75
HALO = 0.7                     # of the hero's outline gap and band
FONT = 5                       # px
CODEX_STROKE = 1.0             # model units; the hero's 0.665 is thinner than a cell at this size
PAD = 2


def frames_of(timeline):
    poses = simulate(timeline)
    for p in poses:
        p["scale"], p["halo"], p["stroke"] = MINI, HALO, CODEX_STROKE
        p["y"] *= MINI / SCALE     # the bob shrinks with the character
    return render_all(poses)


def mini(frames, label, body, outline):
    rows, cols, lines = crop(frames)
    k = FONT / INNER_FONT
    w, h = round(cols * INNER_CW * k + 2 * PAD), round(lines * INNER_CH * k + 2 * PAD)
    art = "".join(frame_group(g, [(BODY_CELLS, "b"), (LINE_CELLS, "o")], f"f{i}", "f", i * TICK)
                  for i, g in enumerate(rows))
    css = (font_css() +
           f".f{{font-size:{INNER_FONT}px;visibility:hidden;animation:f {LOOP * TICK:.3f}s step-end infinite}}"
           f"@keyframes f{{0%{{visibility:visible}}{100 / LOOP:.4f}%{{visibility:hidden}}}}"
           f".b{{fill:{body}}}.o{{fill:{outline}}}"
           "@media (prefers-reduced-motion:reduce){.f{animation:none!important}#f0{visibility:visible}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'xml:space="preserve" role="img" aria-label="{label}"><title>{label}</title>'
            "<!-- Fan art, rendered by scripts/build_minis.py after ghostty.org's terminal animation. Text is set in a subset of\n"
            "     JetBrains Mono, Copyright 2020 The JetBrains Mono Project Authors, SIL Open Font License 1.1. -->"
            f"<style>{css}</style><g transform=\"translate({PAD} {PAD}) scale({fmt(k)})\">{art}</g></svg>"), w, h


def main():
    for name, timeline, label, colour in (("clawd", CLAWD_TL, "Clawd, floating", "accent"),
                                          ("codex", CODEX_TL, "The Codex mark, floating", "codex")):
        frames = frames_of(timeline)
        for mode, theme in PAGE.items():
            svg, w, h = mini(frames, label, theme[colour], theme["outline"])
            path = OUT_DIR / f"mini-{name}-{mode}.svg"
            path.write_text(svg, encoding="utf-8")
        print(f"mini-{name}: {w}x{h}, {len(frames)} frames, {path.stat().st_size / 1024:.0f} KB a theme")


if __name__ == "__main__":
    main()
