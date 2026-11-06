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
LOOKS = [(0.30, 0.13, 0.55, 0.10), (0.73, 0.10, -0.42, -0.08)]  # (centre, half-width, yaw, roll) as loop fractions / radians

# Outline (the halo around the ghost): gap from the body and band width, world units.
HALO_GAP, HALO_W, HALO_PEAK = 5.2, 2.9, 0.72

V = np.array


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


def look(u):
    """Yaw and roll from the two look-arounds, eased in, held, eased out."""
    yaw = roll = 0.0
    for c, hw, y, r in LOOKS:
        d = (u - c + 0.5) % 1.0 - 0.5
        x = abs(d) / hw
        k = float(1 - smoothstep(0.45, 1.0, np.array(x)))
        yaw, roll = yaw + y * k, roll + r * k
    return yaw, roll


def drive(t):
    """The head's own motion at time t (seconds): float, drift, breathe, look."""
    u = (t / (FRAMES * DT)) % 1.0
    ph = 2 * math.pi * u
    yaw, roll = look(u)
    yaw += 0.09 * math.sin(ph + 1.0)
    roll += 0.035 * math.sin(2 * ph + 0.3)
    return {
        "pos": np.array([1.3 * math.sin(ph + 0.4), BOB * math.sin(BOBS * ph), 0.0]),
        "yaw": yaw, "roll": roll,
        "stretch": 1 + 0.032 * math.sin(BOBS * ph),       # longer at the top of a bob, squashed at the bottom
        "blink": min(abs((u - b + 0.5) % 1.0 - 0.5) for b in (0.18, 0.56, 0.62)) * FRAMES < 1.6,
        "ph": ph,
    }


def simulate():
    """Run the springs for three loops, then record one loop of poses."""
    sub = 6
    h = DT / sub
    d0 = drive(0.0)
    body = Spring(d0["pos"], 0.95, 0.26)
    body_turn = Spring([d0["yaw"], d0["roll"]], 1.1, 0.45)
    tip = Spring([0.0, 0.0], 1.55, 0.14)
    legs = Spring([0.0, 0.0], 1.15, 0.22)
    halo = Spring(d0["pos"], 0.95, 0.40)
    halo_turn = Spring([d0["yaw"], d0["roll"]], 0.8, 0.5)
    prev_head = d0["pos"].copy()
    prev_vel = np.zeros(3)
    poses = []
    for frame in range(FRAMES * 4):
        for s in range(sub):
            t = (frame * sub + s) * h
            d = drive(t)
            vel = (d["pos"] - prev_head) / h
            acc = (vel - prev_vel) / h
            prev_head, prev_vel = d["pos"], vel
            b = body.step(d["pos"], h)
            bt = body_turn.step([d["yaw"], d["roll"]], h)
            # The antenna tip is pushed opposite to the head's acceleration and to its turning.
            tip.step([-0.05 * acc[0] - 7.0 * d["roll"], -0.022 * acc[1]], h)
            # Legs dangle from the body: they swing against its sideways motion and paddle a little.
            swing = -0.012 * body.v[0] - 0.9 * bt[1]
            paddle = 0.2 * math.sin(BOBS * d["ph"] - 1.2)
            legs.step([swing + paddle, swing - paddle], h)
            halo.step(d["pos"], h)
            halo_turn.step([d["yaw"], d["roll"]], h)
        if frame >= FRAMES * 3:
            d = drive(frame * DT)
            poses.append({
                "head": d, "body": body.x.copy(), "body_turn": body_turn.x.copy(),
                "tip": tip.x.copy(), "legs": legs.x.copy(),
                "halo": halo.x.copy(), "halo_turn": halo_turn.x.copy(),
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
        ry = EYE_RY * (0.14 if self.blink else 1.0)
        for sx in (-1, 1):
            eye = ((hx - sx * EYE_X) / EYE_RX) ** 2 + ((hy - EYE_Y) / ry) ** 2 < 1
            white[front & eye] = 0
            cheek = (hx - sx * CHEEK_X) ** 2 + (hy - CHEEK_Y) ** 2 < CHEEK_R ** 2
            accent[front & cheek] = 0.62
            white[front & cheek] = 0
        mx = np.clip(hx / MOUTH_W, -1, 1)
        curve = MOUTH_Y - MOUTH_DIP * (1 - mx * mx)
        ends = np.abs(hx) - MOUTH_W
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


def render(pose):
    head = pose["head"]
    fig = Figure(head, pose["body"], pose["body_turn"], pose["tip"], pose["legs"])
    x, y = GX.ravel(), GY.ravel()
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

    # Outline: distance from the lagging, smoothed silhouette, read as the
    # minimum of the field over depth slices.
    hpose = dict(head, pos=pose["halo"], yaw=pose["halo_turn"][0], roll=pose["halo_turn"][1])
    ghost = Figure(hpose, pose["halo"] + (pose["body"] - head["pos"]) * 0.6, pose["halo_turn"], pose["tip"] * 0.5, pose["legs"] * 0.6)
    band = np.nonzero(~covered & (np.abs(x - ghost.hc[0]) < 60) & (y > ghost.hc[1] - 85) & (y < ghost.hc[1] + 60))[0]
    bx, by = x[band], y[band]
    dist = np.full_like(bx, 1e9)
    for z in np.linspace(-34, 34, 18):
        dist = np.minimum(dist, ghost.blob(bx, by, np.full_like(bx, z)))
    centre = ghost.hc + np.array([0, -12.0, 0])
    ang = np.arctan2(by - centre[1], (bx - centre[0]) * 0.8)
    ph = head["ph"]
    gap = HALO_GAP + 0.9 * np.sin(3 * ang + 2 * BOBS * ph) + 0.5 * np.sin(5 * ang - 3 * BOBS * ph + 1.0)
    mid = gap + HALO_W / 2
    halo = HALO_PEAK * np.clip(1 - ((dist - mid) / (HALO_W / 2)) ** 2, 0, 1)
    accent[band] = np.maximum(accent[band], halo)

    # Box-filter the samples into cells, then pick each cell's character the
    # way the video converter does: white by brightness, accent by strength.
    w = white.reshape(ROWS, SUB_Y, COLS, SUB_X).mean(axis=(1, 3))
    a = accent.reshape(ROWS, SUB_Y, COLS, SUB_X).mean(axis=(1, 3))
    lum = 15 + 240 * w
    lines = []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            if lum[r, c] >= 168 and w[r, c] >= a[r, c]:
                row.append(RAMP[min(9, max(0, int((lum[r, c] - 165) * 9 / 90)))])
            elif a[r, c] >= 0.24:
                row.append(ACCENT[min(9, max(0, int(a[r, c] * 9.2)))])
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
