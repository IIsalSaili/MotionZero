"""Enregistrement / relecture des points de la main (JSONL, aucune image).

Une ligne par image : {"t": secondes, "pts": [[x, y] x 21] ou null}
"""
import json

from .config import Config
from .core import Core


def load(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                yield rec["t"], (None if rec["pts"] is None else [tuple(p) for p in rec["pts"]])


def replay(path, cfg=None, screen=(0, 0, 1920, 1080)):
    """Rejoue un enregistrement dans la machine à états. Renvoie [(t, action), ...] hors déplacements."""
    core = Core(cfg or Config(), screen)
    out = []
    for t, pts in load(path):
        for a in core.step(pts, t):
            if a[0] != "move":
                out.append((round(t, 3), a))
    return out
