import json

from synth import hand

from motionzero.config import Config
from motionzero.replay import replay


def test_relecture_d_un_enregistrement(tmp_path):
    path = tmp_path / "rec.jsonl"
    lines, t = [], 0.0

    def add(seconds, pose=None, cx=0.5, to_cx=None):
        nonlocal t
        n = int(seconds * 30)
        for i in range(n):
            t += 1 / 30
            x = cx + ((to_cx if to_cx is not None else cx) - cx) * (i + 1) / n
            lines.append({"t": t, "pts": None if pose is None else [list(p) for p in hand(pose, x)]})

    add(0.5)                        # pas de main
    add(0.5, "open")                # main au centre
    add(0.2, "open", 0.5, 0.9)      # vers le bord droit
    add(0.6, "open", 0.9)           # reste au bord -> page suivante
    path.write_text("\n".join(json.dumps(r) for r in lines), encoding="utf-8")

    actions = [a for _, a in replay(str(path), Config(start_mode="LECTURE"))]
    assert ("key", "right") in actions
