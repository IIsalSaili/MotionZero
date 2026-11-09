"""Mains simulées (21 points) pour tester sans caméra. Repère : poignet à l'origine, y vers le haut négatif."""
import math

MCP = {"index": (-0.25, -0.9), "middle": (-0.05, -1.0), "ring": (0.13, -0.95), "pinky": (0.3, -0.85)}
ORDER = ["index", "middle", "ring", "pinky"]
THUMB_BASE = [(-0.3, -0.25), (-0.5, -0.45), (-0.65, -0.6)]
THUMB_TIP = {"open": (-0.9, -0.7), "folded": (-0.2, -0.6), "up": (-0.45, -1.4)}


SPLAY = {"index": -0.15, "middle": 0.0, "ring": 0.1, "pinky": 0.2}  # doigts écartés comme une vraie main


def _finger(mcp, extended, splay=0.0):
    x, y = mcp
    if extended:
        return [(x, y), (x + splay * 0.45, y - 0.4), (x + splay * 0.7, y - 0.6), (x + splay, y - 0.85)]
    return [(x, y), (x, y - 0.3), (x, y - 0.1), (x, y + 0.1)]


def hand(pose="open", cx=0.5, cy=0.6, scale=0.15):
    ext = {"open": ORDER, "fist": [], "point": ["index"], "thumb_up": [],
           "pinch_left": ORDER, "pinch_right": ORDER}[pose]
    fingers = {n: _finger(MCP[n], n in ext, SPLAY[n]) for n in ORDER}
    thumb_tip = {"open": THUMB_TIP["open"], "fist": THUMB_TIP["folded"], "point": THUMB_TIP["folded"],
                 "thumb_up": THUMB_TIP["up"], "pinch_left": fingers["index"][3],
                 "pinch_right": fingers["middle"][3]}[pose]
    pts = [(0.0, 0.0)] + THUMB_BASE + [thumb_tip]
    for n in ORDER:
        pts += fingers[n]
    return [(cx + x * scale, cy + y * scale) for x, y in pts]


class Clock:
    def __init__(self, fps=30):
        self.t = 0.0
        self.dt = 1.0 / fps

    def run(self, core, seconds, pose="open", cx=0.5, cy=0.6, to_cx=None, to_cy=None, absent=False,
            jitter=0.0):
        """Fait avancer le temps ; renvoie toutes les actions produites.
        jitter : tremblement simulé (amplitude en coordonnées normalisées)."""
        acts = []
        n = max(1, int(round(seconds / self.dt)))
        for i in range(n):
            self.t += self.dt
            k = (i + 1) / n
            x = cx + ((to_cx if to_cx is not None else cx) - cx) * k
            y = cy + ((to_cy if to_cy is not None else cy) - cy) * k
            if jitter:
                x += jitter * math.sin(self.t * 47.0)
                y += jitter * math.cos(self.t * 31.0)
            acts += core.step(None if absent else hand(pose, x, y), self.t)
        return acts
