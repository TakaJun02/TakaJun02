#!/usr/bin/env python3
"""Render Clawd and the Codex mark floating in a terminal, the way ghostty.org shows its ghost.

The method is build_tj02.py's: each frame is ray-marched in 3D, box-filtered
into 100x41 cells and turned into characters with ghostty.org's brightness
rules, and the outline is drawn from the same pose, so it moves with the body.
The characters are the two from the README hero (scripts/build_hero.py):
Clawd as boxes in Claude Code's quadrant-pixel layout, and the Codex mark (its
ring, `>` and `_`) extruded into a thick coin. Both are fan art.

They take turns. Clawd floats, paddles its legs and flaps its arms, then turns
around and melts into the Codex mark (the two shapes' distance fields are
blended), which floats with its `>_` sloshing inside the ring and its cursor
blinking, then turns again and melts back. The springs run through the whole
timeline, so it loops without a seam.

Writes docs/agents-frames.js. Needs numpy. Run:  python3 scripts/build_agents.py
Preview one frame in the terminal:             python3 scripts/build_agents.py --show 40
"""

import argparse
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from build_tj02 import (COLS, ROWS, CHAR_W, CHAR_H, SUB_X, SUB_Y, DT, RAMP,
                        Spring, length, rot, sd_round_box, smin, smoothstep, to_local)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "agents-frames.js"

BODY_CELLS = "ABCDEFGHIJ"      # the character, drawn as RAMP[0-9] in the agent's colour
LINE_CELLS = "KLMNOPQRST"      # its outline, drawn as RAMP[0-9] in the outline colour

# World units are pixels on the 12px terminal. Clawd's quadrant pixels are 1
# model unit wide and 2 tall, and the Codex mark is drawn in a 20-unit box.
# The scales make them about as big as ghostty.org's ghost: the Codex mark
# with its outline is 34 rows tall, and Clawd with its outline 82 columns wide.
CLAWD_S = 29.0                 # pixels per model unit
CODEX_S = 28.0

# Timeline, in 31 ms frames. The bob period is ghostty.org's (48 frames, about
# 1.5 s), and a loop holds a whole number of bobs.
BOB_FRAMES = 48
BOB_PX = 21.0
MORPH = 72                     # frames for one turn while a character melts into the other
CURSOR_ON, CURSOR_PERIOD = 18, 32


@dataclass(frozen=True)
class Timeline:
    """What is keyframed over one loop. Mix 0 is Clawd and 1 the Codex mark."""
    n: int                     # frames in the loop
    glances: tuple = ()        # (centre frame, half-width, yaw, roll)
    blinks: tuple = ()         # frames where Clawd blinks
    melts: tuple = ()          # (start frame, mix before, mix after): a full turn while it melts
    turns: tuple = ()          # (start frame, +1 or -1): a full turn on its own, no melt
    codex: tuple = ()          # (start, end): where the Codex mark floats; its cursor blinks there
    phase: float = 0.0         # bob offset in frames


# The page: each character floats for 4 bobs, then turns and melts into the other.
IDLE = 192
CLAWD_AT, CODEX_AT = 0, IDLE + MORPH
PAGE = Timeline(
    n=2 * (IDLE + MORPH),      # 528 frames, 16.4 s
    glances=((CLAWD_AT + 82, 26, 0.3, 0.05),       # Clawd is a box, so a smaller turn shows its side
             (CODEX_AT + 96, 26, -0.45, -0.05)),
    blinks=(CLAWD_AT + 36, CLAWD_AT + 132, CLAWD_AT + 142),
    melts=((CLAWD_AT + IDLE, 0.0, 1.0), (CODEX_AT + IDLE, 1.0, 0.0)),
    codex=((CODEX_AT, CODEX_AT + IDLE),),
)

# Outline: the same gap and band as TJ-02 and ghostty.org's ghost.
HALO_GAP = 30.0
HALO_W = 14.4

# === Motion ==========================================================================

def smootherstep(s):
    s = min(1.0, max(0.0, s))
    return s * s * s * (s * (6 * s - 15) + 10)


def drive(f, tl):
    """Everything that is keyframed at frame f (a float): float, glance, turn, melt, blinks."""
    n = tl.n
    f = f % n
    ph = 2 * math.pi * (f + tl.phase) / BOB_FRAMES
    yaw = roll = 0.0
    for c, hw, y, r in tl.glances:
        d = (f - c + n / 2) % n - n / 2
        k = float(1 - smoothstep(0.45, 1.0, np.array(abs(d) / hw)))
        yaw, roll = yaw + y * k, roll + r * k
    mix = 1.0 if any(a <= f < b for a, b in tl.codex) else 0.0
    for start, a, b in tl.melts:
        s = (f - start) / MORPH
        if 0 <= s < 1:
            yaw += 2 * math.pi * smootherstep(s)            # one full turn
            m = float(smoothstep(0.3, 0.7, np.array(s)))      # the shapes melt while it faces away
            mix = a + (b - a) * m
    for start, way in tl.turns:
        s = (f - start) / MORPH
        if 0 <= s < 1:
            yaw += way * 2 * math.pi * smootherstep(s)
    blink = any(abs((f - b + n / 2) % n - n / 2) < 1.6 for b in tl.blinks)
    cursor = not any(a <= f < b and int(f - a) % CURSOR_PERIOD >= CURSOR_ON for a, b in tl.codex)
    return {
        "y": BOB_PX * math.sin(ph),
        "stretch": 1 + 0.032 * math.sin(ph),     # longer at the top of a bob, squashed at the bottom
        "yaw": yaw, "roll": roll, "mix": mix, "blink": blink, "cursor": cursor, "ph": ph,
    }


def simulate(tl=PAGE):
    """Run the springs for three loops, then record the fourth."""
    sub = 6
    h = DT / sub
    # Clawd's eight legs paddle in turn and dangle; its arms flap against the bob.
    legs = Spring(np.zeros(8), 1.15, 0.22)
    arms = Spring(np.zeros(2), 1.6, 0.18)
    # The Codex mark's `>_` lags inside the ring.
    inner = Spring(np.zeros(2), 1.3, 0.25)
    leg_phase = np.array([0, math.pi, 0, math.pi] * 2) + np.repeat([0.0, math.pi / 2], 4)
    prev = drive(0.0, tl)
    prev_vy = 0.0
    poses = []
    for frame in range(tl.n * 4):
        for s in range(sub):
            d = drive(frame + s / sub, tl)
            vy = (d["y"] - prev["y"]) / h
            ay = (vy - prev_vy) / h
            vyaw = ((d["yaw"] - prev["yaw"] + math.pi) % (2 * math.pi) - math.pi) / h
            prev, prev_vy = d, vy
            legs.step(0.18 * np.sin(d["ph"] - 1.2 + leg_phase) - 0.9 * d["roll"], h)
            flap = float(np.clip(-6.5e-4 * ay, -0.4, 0.4))
            arms.step([flap + 0.5 * d["roll"], flap - 0.5 * d["roll"]], h)
            inner.step(np.clip([-0.25 * vyaw, -9e-4 * ay], -0.6, 0.6), h)
        if frame >= tl.n * 3:
            pose = drive(frame, tl)
            pose.update(legs=legs.x.copy(), arms=arms.x.copy(), inner=inner.x.copy())
            poses.append(pose)
    return poses

# === The characters ==================================================================
# Each takes world points (pixels) and returns distances in pixels.

LEGS_X = (-6, -4, 4, 6)


def sd_box(x, y, z, cx, cy, cz, bx, by, bz, r=0.12):
    return sd_round_box(x - cx, y - cy, z - cz, bx, by, bz, r)


def sd_segment2(x, y, a, b):
    pax, pay = x - a[0], y - a[1]
    bax, bay = b[0] - a[0], b[1] - a[1]
    t = np.clip((pax * bax + pay * bay) / (bax * bax + bay * bay), 0, 1)
    return np.hypot(pax - bax * t, pay - bay * t)


def extrude(d2, z, half):
    wx, wz = d2, np.abs(z) - half
    return np.minimum(np.maximum(wx, wz), 0) + np.hypot(np.maximum(wx, 0), np.maximum(wz, 0))


class Body:
    """Shared by both characters: where it floats, how it is turned and squashed."""

    def __init__(self, pose, scale):
        self.s = scale
        self.c = np.array([0.0, pose["y"], 0.0])
        self.m = rot(pose["yaw"], pose["roll"])
        self.sy = pose["stretch"]
        self.sxz = 1 / math.sqrt(self.sy)
        self.k = scale * min(self.sy, self.sxz)    # model distance to world distance

    def local(self, x, y, z):
        lx, ly, lz = to_local(x, y, z, self.c, self.m)
        return lx / (self.s * self.sxz), ly / (self.s * self.sy), lz / (self.s * self.sxz)


class Clawd(Body):
    """Clawd from Claude Code as boxes (after build_hero.py)."""

    HALF_D = 3.5

    def __init__(self, pose, mix):
        super().__init__(pose, CLAWD_S * pose.get("scale", 1.0))
        self.legs = pose["legs"]
        self.arms = pose["arms"]
        # Eyes close for a blink, and while Clawd melts into the Codex mark.
        self.open = (0.14 if pose["blink"] else 1.0) * (1 - float(smoothstep(0.05, 0.3, np.array(mix))))

    def parts(self, ux, uy, uz):
        body = sd_box(ux, uy, uz, 0, 1, 0, 6.5, 4, self.HALF_D)
        arms = []
        for side, a in ((-1, self.arms[0]), (1, self.arms[1])):
            # Each arm pivots at the side of the body; a positive angle lifts it.
            ax, ay = side * ux - 6.5, uy
            c, s = math.cos(a), math.sin(a)
            arms.append(sd_box(c * ax + s * ay, -s * ax + c * ay, uz, 0.6, 0, 0, 1.4, 1, 1.5))
        legs = []
        for i, a in enumerate(self.legs):
            # Legs hang from the bottom of the body: a front row and a back row.
            lx, lz = LEGS_X[i % 4], (-1 if i < 4 else 1) * (self.HALF_D - 0.5)
            rx, ry = ux - lx, uy + 3
            c, s = math.cos(a), math.sin(a)
            legs.append(sd_box(c * rx + s * ry, -s * rx + c * ry, uz, 0, -0.8, lz, 0.5, 1.2, 0.5))
        return body, np.minimum(*arms), np.minimum.reduce(legs)

    def sdf(self, x, y, z):
        body, arms, legs = self.parts(*self.local(x, y, z))
        return np.minimum(np.minimum(body, arms), legs) * self.k

    def blob(self, x, y, z):
        """One smooth shape for the outline, with the gaps between the legs filled."""
        ux, uy, uz = self.local(x, y, z)
        body, arms, legs = self.parts(ux, uy, uz)
        feet = sd_box(ux, uy, uz, 0, -4, 0, 6.5, 1, self.HALF_D, 0.4)
        return smin(smin(body, arms, 2.0), np.minimum(legs, feet), 0.6) * self.k

    def eyes(self, x, y, z, facing):
        """True where a hit lands on an eye: two sockets on the front face, row 1."""
        if self.open <= 0.02:
            return np.zeros(x.shape, bool)
        ux, uy, uz = self.local(x, y, z)
        top = 1 + 2 * self.open                 # a closing eye keeps its bottom edge, like `▂`
        on = (uz < 0) & (facing > 0.5) & (uy > 1) & (uy < top)
        return on & ((np.abs(ux - 4) < 0.5) | (np.abs(ux + 4) < 0.5))


class Codex(Body):
    """The Codex mark (openai/codex paths.rs, after build_hero.py) as a coin."""

    HALF_D = 1.3
    STROKE = 0.665
    RING = 7.25

    def __init__(self, pose):
        super().__init__(pose, CODEX_S * pose.get("scale", 1.0))
        self.ox, self.oy = pose["inner"]
        self.cursor = pose["cursor"]

    def sdf(self, x, y, z):
        ux, uy, uz = self.local(x, y, z)
        ring = np.abs(np.hypot(ux, uy) - self.RING) - self.STROKE
        ix, iy = ux - self.ox, uy - self.oy
        mark = np.minimum(sd_segment2(ix, iy, (-2.917, 2.083), (-1.77, 0.0)),
                          sd_segment2(ix, iy, (-1.77, 0.0), (-2.917, -2.083)))
        if self.cursor:
            mark = np.minimum(mark, sd_segment2(ix, iy, (0.833, -2.083), (3.333, -2.083)))
        return extrude(np.minimum(ring, mark - self.STROKE), uz, self.HALF_D) * self.k

    def blob(self, x, y, z):
        ux, uy, uz = self.local(x, y, z)
        return extrude(np.hypot(ux, uy) - self.RING - self.STROKE, uz, self.HALF_D) * self.k


class Scene:
    """One pose: Clawd, the Codex mark, or the two melted together."""

    def __init__(self, pose):
        self.mix = pose["mix"]
        self.clawd = Clawd(pose, self.mix) if self.mix < 1 else None
        self.codex = Codex(pose) if self.mix > 0 else None

    def _blend(self, fa, fb, *p):
        if self.codex is None:
            return fa(*p)
        if self.clawd is None:
            return fb(*p)
        return (1 - self.mix) * fa(*p) + self.mix * fb(*p)

    def sdf(self, x, y, z):
        return self._blend(self.clawd and self.clawd.sdf, self.codex and self.codex.sdf, x, y, z)

    def blob(self, x, y, z):
        return self._blend(self.clawd and self.clawd.blob, self.codex and self.codex.blob, x, y, z)

    def dark(self, x, y, z, facing):
        if self.clawd is None or self.mix >= 0.5:
            return np.zeros(x.shape, bool)
        return self.clawd.eyes(x, y, z, facing)

# === Rendering =======================================================================

def sample_grid():
    cx = (np.arange(COLS * SUB_X) + 0.5) / SUB_X - COLS / 2
    cy = (np.arange(ROWS * SUB_Y) + 0.5) / SUB_Y - ROWS / 2
    return np.meshgrid(cx * CHAR_W, -cy * CHAR_H)


GX, GY = sample_grid()


def render(pose):
    scene = Scene(pose)
    cy = pose["y"]
    x, y = GX.ravel(), GY.ravel()
    body = np.zeros_like(x)

    # The character: orthographic rays along +z, only where it can be.
    idx = np.nonzero((np.abs(x) < 300) & (np.abs(y - cy) < 260))[0]
    rx, ry = x[idx], y[idx]
    rz = np.full_like(rx, -320.0)
    hit = np.zeros(rx.shape, bool)
    live = np.ones(rx.shape, bool)
    for _ in range(140):
        if not live.any():
            break
        li = np.nonzero(live)[0]
        d = scene.sdf(rx[li], ry[li], rz[li])
        rz[li] += d * 0.85
        h = d < 0.05
        hit[li[h]] = True
        live[li[h | (rz[li] > 320)]] = False
    hi = np.nonzero(hit)[0]
    px, py, pz = rx[hi], ry[hi], rz[hi]
    e = 0.25
    nx = scene.sdf(px + e, py, pz) - scene.sdf(px - e, py, pz)
    ny = scene.sdf(px, py + e, pz) - scene.sdf(px, py - e, pz)
    nz = scene.sdf(px, py, pz + e) - scene.sdf(px, py, pz - e)
    facing = -nz / np.maximum(length(nx, ny, nz), 1e-9)
    # Faces towards the viewer get the flat bright fill (`$`). Both characters
    # are made of flat faces, so a face turned away steps down the ramp
    # (`% * =`) and the sides of the boxes and the coin's edge read as depth.
    # The eyes are dark.
    shade = np.where(facing > 0.8, 0.972, 0.84 + 0.16 * facing)
    shade[scene.dark(px, py, pz, facing)] = 0
    body[idx[hi]] = shade
    covered = np.zeros_like(x, bool)
    covered[idx[hi]] = True

    # The outline: distance from this pose's silhouette (the minimum of the
    # field over depth slices), on a rectangle of samples so its gradient tells
    # top and bottom edges from the sides.
    r0 = max(0, int(np.searchsorted(-GY[:, 0], -(cy + 330))))
    r1 = min(GY.shape[0], int(np.searchsorted(-GY[:, 0], -(cy - 330))))
    c0 = max(0, int(np.searchsorted(GX[0], -340)))
    c1 = min(GX.shape[1], int(np.searchsorted(GX[0], 340)))
    bx, by = GX[r0:r1, c0:c1], GY[r0:r1, c0:c1]
    dist = np.full(bx.shape, 1e9)
    for z in np.linspace(-260, 260, 26):
        dist = np.minimum(dist, scene.blob(bx, by, np.full_like(bx, z)))
    gy, gx = np.gradient(dist, CHAR_H / SUB_Y, CHAR_W / SUB_X)
    upright = gy * gy / np.maximum(gx * gx + gy * gy, 1e-9)       # 1 on top/bottom edges, 0 on sides
    inside = (dist >= HALO_GAP) & (dist < HALO_GAP + HALO_W * (1 + 0.45 * upright))
    band = np.zeros(GX.shape)
    flat = np.zeros(GX.shape)
    band[r0:r1, c0:c1] = inside
    flat[r0:r1, c0:c1] = inside * upright
    band = band.ravel() * ~covered
    flat = flat.ravel() * ~covered

    def cells(v):
        return v.reshape(ROWS, SUB_Y, COLS, SUB_X).mean(axis=(1, 3))
    b, cov = cells(body), cells(band)
    ori = cells(flat) / np.maximum(cov, 1e-9)
    lum = 15 + 240 * b
    lines = []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            if lum[r, c] >= 168:
                row.append(BODY_CELLS[min(9, max(0, int((lum[r, c] - 165) * 9 / 90)))])
            elif cov[r, c] >= 0.22:
                level = max(0, round(cov[r, c] * 6) - 1)
                if ori[r, c] > 0.7:
                    level += 2 if ori[r, c] > 0.9 and cov[r, c] >= 0.8 else 1
                row.append(LINE_CELLS[level])
            else:
                row.append(" ")
        lines.append("".join(row).rstrip())
    return "\n".join(lines)


def show(frame, mix):
    body = "38;2;215;119;87" if mix < 0.5 else "38;2;99;168;248"
    for i in range(10):
        frame = frame.replace(BODY_CELLS[i], f"\x1b[{body}m{RAMP[i]}\x1b[0m")
        frame = frame.replace(LINE_CELLS[i], f"\x1b[38;2;195;195;196m{RAMP[i]}\x1b[0m")
    print(frame)


def render_all(poses):
    """Render many poses on all cores."""
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        return list(pool.map(render, poses, chunksize=8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, help="print this frame and stop")
    args = ap.parse_args()
    poses = simulate()
    if args.show is not None:
        pose = poses[args.show % PAGE.n]
        show(render(pose), pose["mix"])
        return
    frames = render_all(poses)
    OUT.parent.mkdir(exist_ok=True)
    body = ",\n".join(json.dumps(f, ensure_ascii=False) for f in frames)
    mix = ",".join(f"{p['mix']:.3g}" for p in poses)
    OUT.write_text(
        "// Generated by scripts/build_agents.py. One string per frame, rows split by \\n.\n"
        "// A-J are the character and K-T its outline: the page draws both as RAMP[0-9],\n"
        "// in <span class=\"b\"> and <span class=\"o\">. AGENT_MIX is 0 for Clawd, 1 for the Codex mark.\n"
        f"window.AGENT_FRAMES = [\n{body}\n];\n"
        f"window.AGENT_MIX = [{mix}];\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(frames)} frames, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
