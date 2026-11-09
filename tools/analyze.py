"""Analyse d'un enregistrement guidé : poses reconnues par phase, distances de pincement, gestes détectés."""
import json
import sys
from collections import Counter, defaultdict

from motionzero.config import Config
from motionzero.gestures import PinchDetector, SwipeDetector
from motionzero.hand import compute_features

cfg = Config()
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
by_phase = defaultdict(list)
for r in rows:
    by_phase[r["phase"]].append(r)

print(f"images: {len(rows)}, duree: {rows[-1]['t']:.1f} s, img/s: {len(rows) / rows[-1]['t']:.1f}")
for phase, rs in by_phase.items():
    feats = [(r["t"], compute_features([tuple(p) for p in r["pts"]], cfg)) for r in rs if r["pts"]]
    poses = Counter(f.pose for _, f in feats)
    present = 100 * len(feats) / len(rs)
    line = f"\n[{phase}] {len(rs)} images, main {present:.0f} %, poses: {dict(poses.most_common())}"
    if feats:
        pi = sorted(f.pinch_index for _, f in feats)
        line += f"\n   pouce-index : min {pi[0]:.2f}  mediane {pi[len(pi) // 2]:.2f}  max {pi[-1]:.2f}"
        sizes = sorted(f.size for _, f in feats)
        line += f"   taille main : {sizes[len(sizes) // 2]:.3f}"
    print(line)
    if phase == "pinch":
        det, events = PinchDetector(cfg), []
        for t, f in feats:
            ev = det.update(f, t)
            if ev:
                events.append((round(t, 2), ev[0], ev[1], round(ev[2], 2) if len(ev) > 2 else ""))
        print("   pincements detectes :", events)
        print("   suite pouce-index :", " ".join(f"{f.pinch_index:.2f}" for _, f in feats))
    if phase == "swipe":
        det, events = SwipeDetector(cfg), []
        for t, f in feats:
            r = det.update(f.palm[0], f.palm[1], t, True)
            if r:
                events.append((round(t, 2), r))
        print("   balayages detectes :", events)
        print("   x paume :", " ".join(f"{f.palm[0]:.2f}" for _, f in feats))
