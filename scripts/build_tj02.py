#!/usr/bin/env python3
"""Render TJ-02 floating in a terminal, the way ghostty.org shows its ghost.

ghostty.org plays a 3D animation as text: each frame of a video is scaled down
to 100 columns, every pixel becomes one character from the ramp `·~ox+=*%$@` by
its brightness, and the coloured outline is wrapped in <span class="b">.
This script does the same, but renders the frames itself: TJ-02 (the robot
from the activity card) is ray-marched in 3D, box-filtered into 100x41 cells
and converted with the same brightness rules.

The motion is simulated, not keyframed: the head bobs and looks around, and
springs drag the antenna, the body, the legs and the outline behind it. The
simulation runs for a few loops first, so the recorded loop is already in its
steady state and repeats without a seam.

Writes docs/frames.js. Needs numpy. Run:  python3 scripts/build_tj02.py
Preview one frame in the terminal:        python3 scripts/build_tj02.py --show 40
"""

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "frames.js"

# Terminal grid, same as ghostty.org: 100 columns x 41 rows, 31 ms a frame.
COLS, ROWS = 100, 41
CHAR_W, CHAR_H = 7.2, 15.84    # JetBrains Mono at 12px: 0.6em advance, 1.32 line height
SUB_X, SUB_Y = 3, 6            # samples per cell; averaging them is the video downscale
FRAMES = 240                   # one loop: 240 x 31 ms = 7.44 s
DT = 0.031
PX = 4.85                      # pixels per world unit
FIG_CY = -1.4                  # world y shown at the middle row
RAMP = "·~ox+=*%$@"
ACCENT = "ABCDEFGHIJ"          # accent glyph levels; the page maps them back into RAMP inside <span class="b">

# Motion
BOBS = 5                       # bobs per loop (about 1.5 s each, like the ghost)
BOB = 4.3                      # bob amplitude, world units
LOOKS = [(0.20, 0.10, 0.45, 0.05)]  # (centre, half-width, yaw, roll): one glance per loop, like the ghost's lean

# Outline, measured from ghostty.org's frames: it keeps a fixed gap of 4 columns
# from the body and is 2 columns wide (`==` at the sides, `**` along the top and
# bottom). It is part of the same pose, so it moves exactly with the body.
HALO_GAP = 30.0 / PX           # 30 px, a little over 4 columns
HALO_W = 14.4 / PX             # 2 columns

# === Small vector helpers ============================================================

def length(x, y, z):
    return np.sqrt(x * x + y * y + z * z)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1 - h)


def rot(yaw, roll):
    """Rotation matrix: roll about the view axis, then yaw about the vertical axis."""
    cy, sy, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(roll), math.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return ry @ rz


def to_local(px, py, pz, centre, m):
    """World points into a part's frame (m maps local to world)."""
    x, y, z = px - centre[0], py - centre[1], pz - centre[2]
    return (m[0, 0] * x + m[1, 0] * y + m[2, 0] * z,
            m[0, 1] * x + m[1, 1] * y + m[2, 1] * z,
            m[0, 2] * x + m[1, 2] * y + m[2, 2] * z)


def sd_round_box(x, y, z, bx, by, bz, r):
    qx, qy, qz = np.abs(x) - (bx - r), np.abs(y) - (by - r), np.abs(z) - (bz - r)
    outside = length(np.maximum(qx, 0), np.maximum(qy, 0), np.maximum(qz, 0))
    inside = np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0)
    return outside + inside - r


def sd_capsule(x, y, z, a, b, r):
    bax, bay, baz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    pax, pay, paz = x - a[0], y - a[1], z - a[2]
    h = np.clip((pax * bax + pay * bay + paz * baz) / (bax * bax + bay * bay + baz * baz), 0, 1)
    return length(pax - bax * h, pay - bay * h, paz - baz * h) - r


# === TJ-02 ===========================================================================
# Proportions follow the activity card (head 68x48 with r12, body 40x18 with r5,
# antenna 12 tall with a ball, two short legs), turned into rounded solids.

HEAD = (34.0, 24.0, 21.0, 15.5)        # half extents and corner radius
PUFF = 2.2                             # how far the middle of each face bulges out
BODY = (20.0, 9.0, 13.0, 6.5)
HEAD_Y, BODY_Y = 8.0, -27.0            # rest centres (world y, up is +)
HIP_Y, LEG_X, LEG_LEN, LEG_R = -36.0, 10.0, 12.0, 2.7
STALK_LEN, STALK_R, BALL_R = 13.0, 1.5, 4.6
EYE_X, EYE_Y, EYE_RX, EYE_RY = 13.5, 4.0, 3.9, 4.5
CHEEK_X, CHEEK_Y, CHEEK_R = 23.0, -4.5, 4.2
MOUTH_Y, MOUTH_W, MOUTH_DIP, MOUTH_T = -8.5, 7.5, 3.4, 1.45
DOT_R = 3.0


@dataclass(frozen=True)
class Mood:
    """How TJ-02 floats and what its face shows. The defaults are the page's;
    scripts/build_activity_art.py varies them for the Activity window."""
    bobs: int = BOBS                       # bobs per loop
    bob: float = BOB                       # amplitude, world units
    looks: tuple = tuple(LOOKS)
    blinks: tuple = (0.18, 0.56, 0.62)     # where in the loop it blinks
    closed: bool = False                   # eyes shut the whole loop
    smile: float = 1.0                     # how far the mouth dips; 0 is a straight line
    mouth_w: float = MOUTH_W
    tilt: float = 0.0                      # a constant roll, for a head that has nodded off


PAGE_MOOD = Mood()


class Spring:
    """A damped spring that chases a target: the source of all the lag and wobble."""

    def __init__(self, value, freq, damping):
        self.x = np.array(value, float)
        self.v = np.zeros_like(self.x)
        self.w, self.z = 2 * math.pi * freq, damping

    def step(self, target, dt):
        a = self.w * self.w * (np.asarray(target) - self.x) - 2 * self.z * self.w * self.v
        self.v = self.v + a * dt
        self.x = self.x + self.v * dt
        return self.x


def look(u, looks=tuple(LOOKS)):
    """Yaw and roll from the look-arounds, eased in, held, eased out."""
    yaw = roll = 0.0
    for c, hw, y, r in looks:
        d = (u - c + 0.5) % 1.0 - 0.5
        x = abs(d) / hw
        k = float(1 - smoothstep(0.45, 1.0, np.array(x)))
        yaw, roll = yaw + y * k, roll + r * k
    return yaw, roll


def drive(t, mood=PAGE_MOOD):
    """The head's own motion at time t (seconds): float, breathe, glance, blink."""
    u = (t / (FRAMES * DT)) % 1.0
    ph = 2 * math.pi * u
    yaw, roll = look(u, mood.looks)
    return {
        "pos": np.array([0.0, mood.bob * math.sin(mood.bobs * ph), 0.0]),
        "yaw": yaw, "roll": roll + mood.tilt,
        "stretch": 1 + 0.032 * math.sin(mood.bobs * ph),  # longer at the top of a bob, squashed at the bottom
        "blink": any(abs((u - b + 0.5) % 1.0 - 0.5) * FRAMES < 1.6 for b in mood.blinks),
        "closed": mood.closed, "smile": mood.smile, "mouth_w": mood.mouth_w,
        "ph": ph,
    }


def simulate(mood=PAGE_MOOD):
    """Run the springs for three loops, then record one loop of poses."""
    sub = 6
    h = DT / sub
    d0 = drive(0.0, mood)
    # The body follows the head closely, so the robot moves as one piece; the
    # antenna and the legs are the loose ends, like the ghost's hem.
    body = Spring(d0["pos"], 2.6, 0.6)
    body_turn = Spring([d0["yaw"], d0["roll"]], 2.6, 0.6)
    tip = Spring([0.0, 0.0], 1.55, 0.14)
    legs = Spring([0.0, 0.0], 1.15, 0.22)
    prev_head = d0["pos"].copy()
    prev_vel = np.zeros(3)
    poses = []
    for frame in range(FRAMES * 4):
        for s in range(sub):
            t = (frame * sub + s) * h
            d = drive(t, mood)
            vel = (d["pos"] - prev_head) / h
            acc = (vel - prev_vel) / h
            prev_head, prev_vel = d["pos"], vel
            b = body.step(d["pos"], h)
            bt = body_turn.step([d["yaw"], d["roll"]], h)
            # The antenna tip is pushed opposite to the head's acceleration and to its turning.
            tip.step([-0.05 * acc[0] - 7.0 * d["roll"], -0.022 * acc[1]], h)
            # Legs dangle from the body: they swing against its sideways motion and paddle a little.
            swing = -0.012 * body.v[0] - 0.9 * bt[1]
            paddle = 0.2 * math.sin(mood.bobs * d["ph"] - 1.2)
            legs.step([swing + paddle, swing - paddle], h)
        if frame >= FRAMES * 3:
            d = drive(frame * DT, mood)
            poses.append({
                "head": d, "body": body.x.copy(), "body_turn": body_turn.x.copy(),
                "tip": tip.x.copy(), "legs": legs.x.copy(),
            })
    return poses


class Figure:
    """TJ-02 in one pose: signed distance, materials and face paint."""

    def __init__(self, head, body, body_turn, tip, legs):
        self.hc = np.array([0.0, HEAD_Y, 0.0]) + head["pos"]
        self.hm = rot(head["yaw"], head["roll"])
        self.sy = head["stretch"]
        self.sxz = 1 / math.sqrt(self.sy)
        self.blink = head["blink"]
        self.closed = head.get("closed", False)
        self.smile = head.get("smile", 1.0)
        self.mouth_w = head.get("mouth_w", MOUTH_W)
        self.bc = np.array([0.0, BODY_Y, 0.0]) + body
        self.bm = rot(body_turn[0], body_turn[1])
        # Antenna: base on top of the head, tip bent by the spring, both in head space.
        base = np.array([0.0, HEAD[1] * self.sy - 1.0, 0.0])
        tipl = np.array([tip[0], HEAD[1] * self.sy + PUFF + STALK_LEN + tip[1], 0.0])
        mid = (base + tipl) / 2 + np.array([tip[0] * 0.35, 0.0, 0.0])
        self.stalk = [self.hm @ p + self.hc for p in (base, mid, tipl)]
        self.ball = self.hm @ (tipl + np.array([0, BALL_R * 0.75, 0])) + self.hc
        # Legs hang from the body's hips.
        self.legs = []
        for side, ang in ((-1, legs[0]), (1, legs[1])):
            hip = self.bm @ np.array([side * LEG_X, HIP_Y - BODY_Y + 1.5, 0.0]) + self.bc
            foot = hip + np.array([math.sin(ang) * LEG_LEN, -math.cos(ang) * LEG_LEN, 0.0])
            self.legs.append((hip, foot))

    def parts(self, x, y, z):
        hx, hy, hz = to_local(x, y, z, self.hc, self.hm)
        ux, uy, uz = hx / self.sxz, hy / self.sy, hz / self.sxz
        puff = PUFF * np.clip(1 - (ux / HEAD[0]) ** 2, 0, 1) * np.clip(1 - (uy / HEAD[1]) ** 2, 0, 1)
        head = (sd_round_box(ux, uy, uz, *HEAD) - puff) * min(self.sy, self.sxz)
        bx, by, bz = to_local(x, y, z, self.bc, self.bm)
        body = sd_round_box(bx, by, bz, *BODY)
        legs = np.minimum(*(sd_capsule(x, y, z, a, b, LEG_R) for a, b in self.legs))
        s0, s1, s2 = self.stalk
        stalk = np.minimum(sd_capsule(x, y, z, s0, s1, STALK_R), sd_capsule(x, y, z, s1, s2, STALK_R))
        ball = length(x - self.ball[0], y - self.ball[1], z - self.ball[2]) - BALL_R
        return head, body, legs, stalk, ball

    def sdf(self, x, y, z):
        return np.minimum.reduce(self.parts(x, y, z))

    def blob(self, x, y, z):
        """One smooth shape around the head, body and legs, for the outline.
        The antenna is left out, so it pokes through the outline."""
        head, body, legs, stalk, ball = self.parts(x, y, z)
        (a0, f0), (a1, f1) = self.legs
        feet = sd_capsule(x, y, z, (a0 + f0) / 2, (a1 + f1) / 2, LEG_R + 3.0)
        d = smin(head, body, 10.0)
        return smin(d, smin(legs, feet, 6.0), 8.0)

    def paint(self, x, y, z, part):
        """Per hit: white value (0 for dark paint) and accent value."""
        white = np.ones_like(x)
        accent = np.zeros_like(x)
        hx, hy, hz = to_local(x, y, z, self.hc, self.hm)
        hx, hy = hx / self.sxz, hy / self.sy
        front = (part == 0) & (hz < 0)
        # A blink is a slit; eyes shut for good are a thicker line, so they
        # still show when the robot is drawn small.
        ry = EYE_RY * (0.4 if self.closed else 0.14 if self.blink else 1.0)
        for sx in (-1, 1):
            eye = ((hx - sx * EYE_X) / EYE_RX) ** 2 + ((hy - EYE_Y) / ry) ** 2 < 1
            white[front & eye] = 0
            cheek = (hx - sx * CHEEK_X) ** 2 + (hy - CHEEK_Y) ** 2 < CHEEK_R ** 2
            accent[front & cheek] = 0.62
            white[front & cheek] = 0
        mx = np.clip(hx / self.mouth_w, -1, 1)
        curve = MOUTH_Y - MOUTH_DIP * self.smile * (1 - mx * mx)
        ends = np.abs(hx) - self.mouth_w
        mouth = np.sqrt(np.maximum(ends, 0) ** 2 + (hy - np.where(ends > 0, MOUTH_Y, curve)) ** 2) < MOUTH_T
        white[front & mouth] = 0
        bx, by, bz = to_local(x, y, z, self.bc, self.bm)
        dot = (part == 1) & (bz < 0) & (bx * bx + by * by < DOT_R * DOT_R)
        white[dot], accent[dot] = 0, 1.0
        ball = part == 4
        white[ball], accent[ball] = 0, 1.0
        return white, accent


# === Rendering =======================================================================

def sample_grid():
    cx = (np.arange(COLS * SUB_X) + 0.5) / SUB_X - COLS / 2
    cy = (np.arange(ROWS * SUB_Y) + 0.5) / SUB_Y - ROWS / 2
    gx, gy = np.meshgrid(cx * CHAR_W / PX, -cy * CHAR_H / PX + FIG_CY)
    return gx, gy


GX, GY = sample_grid()


def render(pose, scale=1.0, halo=1.0):
    """One frame as text. `scale` draws the robot smaller on the same grid;
    the outline keeps its gap and width in pixels, as the README hero's do,
    times `halo`."""
    head = pose["head"]
    fig = Figure(head, pose["body"], pose["body_turn"], pose["tip"], pose["legs"])
    gxs, gys = (GX, GY) if scale == 1.0 else (GX / scale, GY / scale)
    halo_gap, halo_w = HALO_GAP * halo / scale, HALO_W * halo / scale
    x, y = gxs.ravel(), gys.ravel()
    white = np.zeros_like(x)
    accent = np.zeros_like(x)

    # Body: march orthographic rays along +z, only where the robot can be.
    near = (np.abs(x - fig.hc[0]) < 48) & (y > fig.hc[1] - 75) & (y < fig.hc[1] + 50)
    idx = np.nonzero(near)[0]
    rx, ry = x[idx], y[idx]
    rz = np.full_like(rx, -60.0)
    hit = np.zeros(rx.shape, bool)
    live = np.ones(rx.shape, bool)
    for _ in range(110):
        if not live.any():
            break
        li = np.nonzero(live)[0]
        d = fig.sdf(rx[li], ry[li], rz[li])
        rz[li] += d * 0.85
        h = d < 0.01
        hit[li[h]] = True
        gone = h | (rz[li] > 60)
        live[li[gone]] = False
    hi = np.nonzero(hit)[0]
    px, py, pz = rx[hi], ry[hi], rz[hi]
    e = 0.05
    nz = (fig.sdf(px, py, pz + e) - fig.sdf(px, py, pz - e))
    nx = (fig.sdf(px + e, py, pz) - fig.sdf(px - e, py, pz))
    ny = (fig.sdf(px, py + e, pz) - fig.sdf(px, py - e, pz))
    facing = -nz / np.maximum(length(nx, ny, nz), 1e-9)
    part = np.argmin(np.stack(fig.parts(px, py, pz)), axis=0)
    w, a = fig.paint(px, py, pz, part)
    # Flat bright fill, brighter at grazing angles: the rim of '@' inside the edge.
    shade = 0.972 + 0.03 * smoothstep(0.42, 0.72, 1 - facing)
    white[idx[hi]] = w * shade
    accent[idx[hi]] = a
    covered = np.zeros_like(x, bool)
    covered[idx[hi]] = True

    # Outline: distance from the silhouette of this same pose, read as the
    # minimum of the field over depth slices, on a rectangle of samples so its
    # gradient tells top/bottom edges from side edges.
    pad = (halo_gap + halo_w) - (HALO_GAP + HALO_W)     # the outline reaches further when drawn small
    r0 = max(0, int(np.searchsorted(-gys[:, 0], -(fig.hc[1] + 58 + pad))))
    r1 = min(gys.shape[0], int(np.searchsorted(-gys[:, 0], -(fig.hc[1] - 80 - pad))))
    c0 = max(0, int(np.searchsorted(gxs[0], fig.hc[0] - 62 - pad)))
    c1 = min(gxs.shape[1], int(np.searchsorted(gxs[0], fig.hc[0] + 62 + pad)))
    bx, by = gxs[r0:r1, c0:c1], gys[r0:r1, c0:c1]
    dist = np.full(bx.shape, 1e9)
    for z in np.linspace(-34, 34, 18):
        dist = np.minimum(dist, fig.blob(bx, by, np.full_like(bx, z)))
    gy, gx = np.gradient(dist, CHAR_H / SUB_Y / PX / scale, CHAR_W / SUB_X / PX / scale)
    upright = gy * gy / np.maximum(gx * gx + gy * gy, 1e-9)       # 1 on top/bottom edges, 0 on sides
    band = np.zeros(GX.shape)
    flat = np.zeros(GX.shape)
    # Along the top and bottom the band is a little thicker, so it fills a row
    # like the ghost's bright top edge does.
    inside = (dist >= halo_gap) & (dist < halo_gap + halo_w * (1 + 0.45 * upright))
    band[r0:r1, c0:c1] = inside
    flat[r0:r1, c0:c1] = inside * upright
    band = band.ravel() * ~covered
    flat = flat.ravel() * ~covered

    # Box-filter the samples into cells, then pick each cell's character the
    # way the video converter does: white by brightness, accent by strength,
    # and the outline by how much of the cell it fills.
    def cells(v):
        return v.reshape(ROWS, SUB_Y, COLS, SUB_X).mean(axis=(1, 3))
    w, a, cov = cells(white), cells(accent), cells(band)
    ori = cells(flat) / np.maximum(cov, 1e-9)
    lum = 15 + 240 * w
    lines = []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            if lum[r, c] >= 168 and w[r, c] >= a[r, c]:
                row.append(RAMP[min(9, max(0, int((lum[r, c] - 165) * 9 / 90)))])
            elif a[r, c] >= 0.24:
                row.append(ACCENT[min(9, max(0, int(a[r, c] * 9.2)))])
            elif cov[r, c] >= 0.22:
                # A fully covered cell is `=`; one the band only partly covers
                # fades through `+ x o ~ ·`, as the ghost's outline does when
                # it slides across the columns. Top and bottom edges are
                # brighter (`*`, `%`).
                level = max(0, round(cov[r, c] * 6) - 1)
                if ori[r, c] > 0.7:
                    level += 2 if ori[r, c] > 0.9 and cov[r, c] >= 0.8 else 1
                row.append(ACCENT[level])
            else:
                row.append(" ")
        lines.append("".join(row).rstrip())
    return "\n".join(lines)


def show(frame):
    txt = frame
    for i, ch in enumerate(ACCENT):
        txt = txt.replace(ch, f"\x1b[38;2;217;119;87m{RAMP[i]}\x1b[0m")
    print(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, help="print this frame and stop")
    args = ap.parse_args()
    poses = simulate()
    if args.show is not None:
        show(render(poses[args.show % FRAMES]))
        return
    frames = [render(p) for p in poses]
    OUT.parent.mkdir(exist_ok=True)
    body = ",\n".join(json.dumps(f, ensure_ascii=False) for f in frames)
    OUT.write_text(
        "// Generated by scripts/build_tj02.py. One string per frame, rows split by \\n.\n"
        "// A-J are accent cells: the page draws them as RAMP[0-9] inside <span class=\"b\">.\n"
        f"window.TJ02_FRAMES = [\n{body}\n];\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(frames)} frames, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
