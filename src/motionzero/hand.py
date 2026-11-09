"""Caractéristiques de la main à partir des 21 points MediaPipe (coordonnées normalisées, image en miroir)."""
import math
from dataclasses import dataclass

# (base, articulation du milieu, bout) pour chaque doigt
FINGERS = {"index": (5, 6, 8), "middle": (9, 10, 12), "ring": (13, 14, 16), "pinky": (17, 18, 20)}
PALM_POINTS = (0, 5, 9, 13, 17)


class Pose:
    OPEN = "OUVERTE"
    FIST = "POING"
    POINT = "INDEX"
    THUMB_UP = "POUCE"
    OTHER = "AUTRE"


@dataclass
class HandFeatures:
    palm: tuple            # centre de la paume (x, y)
    size: float            # poignet -> base du majeur
    extended: dict         # doigt -> tendu ?
    thumb_extended: bool
    pinch_index: float     # pouce-index / taille
    pinch_middle: float    # pouce-majeur / taille
    pose: str


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dr(a, b, aspect):
    """Distance réelle dans l'image : x est normalisé par la largeur, y par la hauteur.
    Sans ce facteur, un même pincement mesure autrement main droite ou main de côté."""
    return math.hypot((a[0] - b[0]) * aspect, a[1] - b[1])


def palm_center(pts):
    return (sum(pts[i][0] for i in PALM_POINTS) / 5, sum(pts[i][1] for i in PALM_POINTS) / 5)


def pick_hand(hands, previous_palm=None):
    """Main gauche ou droite indifféremment. Si deux mains sont visibles, on garde celle qu'on suivait
    (paume la plus proche de la précédente) ; sinon la plus grande (la plus proche de la caméra)."""
    if not hands:
        return None
    if len(hands) == 1:
        return hands[0]
    if previous_palm is not None:
        return min(hands, key=lambda h: _d(palm_center(h), previous_palm))
    return max(hands, key=lambda h: _d(h[0], h[9]))


class HandTracker:
    """Suit les DEUX mains (gauche et droite indifféremment). La main « active » est celle qui bouge :
    une main posée immobile ne vole pas la main. Une main perdue 1 à 3 images est conservée (bruit)."""

    def __init__(self, match_dist=0.25, max_missing=3, switch_margin=0.15, speed_alpha=0.3):
        self.match_dist = match_dist
        self.max_missing = max_missing
        self.switch_margin = switch_margin
        self.alpha = speed_alpha
        self.tracks = []
        self.active_id = None
        self._next_id = 0

    def update(self, hands, t):
        palms = [palm_center(h) for h in hands]
        free = list(range(len(hands)))
        for tr in sorted(self.tracks, key=lambda tr: tr["missing"]):
            tr["matched"] = False
            if not free:
                continue
            j = min(free, key=lambda k: _d(palms[k], tr["palm"]))
            if _d(palms[j], tr["palm"]) <= self.match_dist:
                dt = max(t - tr["last_t"], 1e-3)
                v = _d(palms[j], tr["palm"]) / dt
                tr.update(speed=self.alpha * v + (1 - self.alpha) * tr["speed"], palm=palms[j],
                          pts=hands[j], missing=0, last_t=t, matched=True)
                free.remove(j)
        for tr in self.tracks:
            if not tr["matched"]:
                tr["missing"] += 1
        self.tracks = [tr for tr in self.tracks if tr["missing"] <= self.max_missing]
        for j in free:
            self.tracks.append({"id": self._next_id, "palm": palms[j], "pts": hands[j], "speed": 0.0,
                                "missing": 0, "last_t": t, "matched": True})
            self._next_id += 1

        by_id = {tr["id"]: tr for tr in self.tracks}
        active = by_id.get(self.active_id)
        visible = [tr for tr in self.tracks if tr["missing"] == 0]
        if active is None:
            active = max(visible, key=lambda tr: tr["speed"], default=None)
        else:
            others = [tr for tr in visible if tr is not active]
            best = max(others, key=lambda tr: tr["speed"], default=None)
            if best is not None and best["speed"] > active["speed"] + self.switch_margin:
                active = best
        self.active_id = active["id"] if active else None
        return active["pts"] if active else None


def compute_features(pts, cfg) -> HandFeatures:
    wrist = pts[0]
    k = cfg.width / cfg.height
    d = lambda a, b: _dr(a, b, k)
    size = d(pts[0], pts[9]) or 1e-6
    extended = {name: d(pts[tip], wrist) > d(pts[pip], wrist) * cfg.finger_ext_ratio
                for name, (_, pip, tip) in FINGERS.items()}
    thumb_ext = d(pts[4], pts[5]) / size > cfg.thumb_ext_dist
    palm = palm_center(pts)
    n =sum(extended.values())
    if n == 4 and thumb_ext:
        pose = Pose.OPEN
    elif n == 0 and not thumb_ext:
        pose = Pose.FIST
    elif n == 1 and extended["index"]:
        pose = Pose.POINT
    elif n == 0 and thumb_ext and pts[4][1] < pts[5][1] - cfg.thumb_up_margin * size:
        pose = Pose.THUMB_UP
    else:
        pose = Pose.OTHER
    return HandFeatures(palm, size, extended, thumb_ext,
                        d(pts[4], pts[8]) / size, d(pts[4], pts[12]) / size, pose)
