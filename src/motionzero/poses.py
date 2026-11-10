"""Reconnaissance des poses par les angles des doigts en 3D, réglée sur la main de l'utilisateur.

Pourquoi : mesurées à plat sur l'image, les distances trompent selon l'orientation de la main
(un poing tourné vers la caméra, une main ouverte détendue prise pour un poing). Les angles des
articulations, calculés sur les points 3D « monde » de MediaPipe, ne dépendent pas de la caméra.

Principe :
- chaque doigt (index, majeur, annulaire, auriculaire) donne sa pliure totale en degrés
  (0 = tendu, ~230 = replié) ;
- chaque doigt est tendu, plié ou incertain, selon des seuils tirés des poses enregistrées par
  l'utilisateur (calibration/poses.json) ; main ouverte = 4 doigts tendus, quelle que soit l'ouverture ;
- un doigt incertain, ou une combinaison inconnue : INCERTAIN, et rien ne se déclenche ;
- une pose ne compte qu'après avoir été vue sur 6 des 8 dernières images (~0,4 s à 20 images/s).
"""
import json
import math
from collections import Counter, deque

FINGERS = {"index": (0, 5, 6, 7, 8), "middle": (0, 9, 10, 11, 12),
           "ring": (0, 13, 14, 15, 16), "pinky": (0, 17, 18, 19, 20)}
UNSURE = "INCERTAIN"
LABELS = {"open": "MAIN OUVERTE", "closed": "MAIN FERMEE", "point": "INDEX", UNSURE: UNSURE}

EXT_MARGIN_DEG = 35.0   # tendu jusqu'au repère « main ouverte » + 35° (main détendue comprise)
CURL_MARGIN_DEG = 20.0  # plié à partir du repère « plié » - 20° ; entre les deux : doigt incertain
VOTE_N, VOTE_K = 8, 6


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _bend(a, b, c):
    """Pliure à l'articulation b (degrés) : 0 si a, b, c sont alignés."""
    u, v = _sub(b, a), _sub(c, b)
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(x * x for x in v))
    if nu < 1e-9 or nv < 1e-9:
        return 0.0
    cos = sum(x * y for x, y in zip(u, v)) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def flexion(world):
    """Pliure totale (MCP + PIP + DIP) de chaque doigt, à partir des 21 points 3D monde."""
    out = []
    for w, m, p, d, t in FINGERS.values():
        out.append(_bend(world[w], world[m], world[p]) + _bend(world[m], world[p], world[d])
                   + _bend(world[p], world[d], world[t]))
    return out


def thresholds(centroids):
    """Seuils par doigt, tirés des poses enregistrées :
    - tendu si la pliure est sous le repère « main ouverte » + marge. Une main plus ouverte
      que la main détendue enregistrée compte donc aussi (main grande ouverte) ;
    - plié si la pliure dépasse le plus petit repère « plié » (main fermée, ou doigts repliés
      de l'index pointé) - marge."""
    ext, curl = [], []
    for i in range(4):
        ext.append(centroids["open"][i] + EXT_MARGIN_DEG)
        bent = [centroids["closed"][i]] + ([centroids["point"][i]] if i > 0 and "point" in centroids else [])
        curl.append(min(bent) - CURL_MARGIN_DEG)
    return ext, curl


def finger_states(f, th):
    """True = tendu, False = plié, None = entre les deux."""
    ext, curl = th
    return [True if x <= e else False if x >= c else None for x, e, c in zip(f, ext, curl)]


POINT_INDEX_MAX = 110.0  # index pointé : pliure de l'index au plus 110°
POINT_GAP_MIN = 60.0     # ... et au moins 60° plus tendu que le plus tendu des 3 autres doigts.
# Index vers la caméra : les autres doigts, cachés, sont « devinés » à demi ouverts par MediaPipe ;
# l'écart avec l'index reste net, alors qu'une main ouverte n'a jamais cet écart (mesuré : -14°).


def classify(f, centroids):
    """(pose, états des doigts). Un doigt incertain, ou une combinaison inconnue : INCERTAIN."""
    st = finger_states(f, thresholds(centroids))
    if f[0] <= POINT_INDEX_MAX and min(f[1:]) - f[0] >= POINT_GAP_MIN:
        return "point", st
    if None in st:
        return UNSURE, st
    if all(st):
        return "open", st
    if not any(st):
        return "closed", st
    return UNSURE, st


class PoseVoter:
    """Une pose n'est retenue que si elle domine les dernières images ; sinon INCERTAIN."""

    def __init__(self, n=VOTE_N, k=VOTE_K):
        self.buf = deque(maxlen=n)
        self.k = k

    def reset(self):
        self.buf.clear()

    def update(self, pose):
        self.buf.append(pose)
        top, count = Counter(self.buf).most_common(1)[0]
        return top if top != UNSURE and count >= self.k else UNSURE


def centroids_from_recording(rows, phases=("open", "closed", "point")):
    """Moyenne des pliures par pose, à partir d'un enregistrement de tools/record_poses.py.
    On ignore la première seconde de chaque pose (le temps de la former)."""
    acc, first = {p: [] for p in phases}, {}
    for r in rows:
        ph = r.get("phase")
        if ph not in acc or not r.get("hands"):
            continue
        first.setdefault(ph, r["t"])
        if r["t"] - first[ph] < 1.0:
            continue
        w = r["hands"][0].get("world")
        if w and len(w) == 21:
            acc[ph].append(flexion(w))
    return {p: [sum(v[i] for v in fs) / len(fs) for i in range(4)] for p, fs in acc.items() if fs}


def load_centroids(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["centroids"]
