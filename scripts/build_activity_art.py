#!/usr/bin/env python3
"""Render TJ-02 for the Activity window, once for every mood.

    python3 scripts/build_activity_art.py            # writes scripts/data/tj02-moods.json.gz
    python3 scripts/build_activity_art.py --show sleepy 40

TJ-02's mood follows the contribution calendar, so the daily job picks one of
these loops; it runs without numpy, so the loops are rendered here, ahead of
time, with docs/index.html's renderer (scripts/build_tj02.py), drawn smaller
the way the README hero draws Clawd and the Codex mark. Each mood is one
240-frame loop (7.44 s, as on ghostty.org); "mini" is the sub-agent a streak
spawns. Frames are text: RAMP characters for the body and A-J for the clay
accents and outline, as in docs/frames.js.

Needs numpy. Rerun it only when TJ-02 or a mood changes.
"""

import argparse
import gzip
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from build_tj02 import ACCENT, Mood, render, show, simulate
from terminal import crop

OUT = Path(__file__).resolve().parent / "data" / "tj02-moods.json.gz"

SCALE = 0.55                   # of the page's robot, drawn in the window's 8 px art font
MINI_SCALE, MINI_HALO = 0.33, 0.5   # sub-agents: a third the size, with an outline half as far out

MOODS = {
    # Fresh commits today: the page's own loop.
    "happy": Mood(),
    # A streak: bobs twice as fast, glances both ways, grins.
    "overclocked": Mood(bobs=10, bob=3.0, smile=1.35, mouth_w=9.0,
                        looks=((0.25, 0.08, 0.35, 0.06), (0.75, 0.08, -0.35, -0.06))),
    # A day or two without commits: a flat mouth, looking around for a push.
    "idle": Mood(smile=0.0, mouth_w=5.5, looks=((0.2, 0.1, 0.45, 0.05), (0.65, 0.1, -0.45, -0.05))),
    # Three to six quiet days: eyes shut, a slow, shallow float.
    "sleepy": Mood(bobs=3, bob=2.4, closed=True, smile=0.0, mouth_w=4.0, blinks=(), looks=()),
    # A week or more: barely breathing, head nodded to one side.
    "hibernating": Mood(bobs=2, bob=1.0, closed=True, smile=0.0, mouth_w=4.0, blinks=(), looks=(), tilt=0.12),
}


def render_scaled(args):
    return render(*args)


def loop(mood, scale, halo, pool):
    """One loop, cut down to the box every frame fits in."""
    poses = simulate(mood)
    frames = list(pool.map(render_scaled, [(p, scale, halo) for p in poses], chunksize=8))
    return ["\n".join(rows) for rows in crop(frames)[0]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", nargs=2, metavar=("MOOD", "FRAME"), help="print one frame and stop")
    args = ap.parse_args()
    if args.show:
        name, frame = args.show
        mood, scale, halo = (MOODS["happy"], MINI_SCALE, MINI_HALO) if name == "mini" else (MOODS[name], SCALE, 1.0)
        show(render(simulate(mood)[int(frame) % 240], scale, halo))
        return
    out = {"scale": SCALE, "accent": ACCENT, "moods": {}}
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        for name, mood in MOODS.items():
            out["moods"][name] = loop(mood, SCALE, 1.0, pool)
            print(f"{name}: {len(out['moods'][name])} frames")
        out["mini"] = loop(MOODS["happy"], MINI_SCALE, MINI_HALO, pool)
    OUT.parent.mkdir(exist_ok=True)
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()
    OUT.write_bytes(gzip.compress(data, 9, mtime=0))
    print(f"{OUT.relative_to(OUT.parents[2])}: {len(data) / 1024:.0f} KB of frames, {OUT.stat().st_size / 1024:.0f} KB gzipped")


if __name__ == "__main__":
    main()
