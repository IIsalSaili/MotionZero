"""Calcule les repères de poses de l'utilisateur à partir d'un enregistrement, et mesure la fiabilité.

  python tools/calibrate_poses.py recordings/poses_calib.jsonl calibration/poses.json
"""
import json
import sys
from collections import Counter, defaultdict

from motionzero.poses import LABELS, UNSURE, PoseVoter, centroids_from_recording, classify, flexion


def main():
    src, dst = sys.argv[1], sys.argv[2]
    rows = [json.loads(line) for line in open(src, encoding="utf-8") if line.strip()]
    cents = centroids_from_recording(rows)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"source": src, "centroids": {k: [round(x, 1) for x in v] for k, v in cents.items()}},
                  fh, indent=2)
    print("Repères (pliure index, majeur, annulaire, auriculaire, en degrés) :")
    for k, v in cents.items():
        print(f"  {LABELS[k]:12} " + "  ".join(f"{x:5.0f}" for x in v))

    raw, voted = defaultdict(Counter), defaultdict(Counter)
    voter = PoseVoter()
    for r in rows:
        if not r.get("hands"):
            voter.reset()
            continue
        pose, _ = classify(flexion(r["hands"][0]["world"]), cents)
        raw[r["phase"]][pose] += 1
        voted[r["phase"]][voter.update(pose)] += 1
    print("\nPose reconnue par phase (image par image | après vote 6 sur 8) :")
    for ph in ("prepare", "open", "closed", "point", "pinch", "pause"):
        if ph in raw:
            fmt = lambda c: ", ".join(f"{LABELS.get(k, k)} {100 * n / sum(c.values()):.0f} %" for k, n in c.most_common())
            print(f"  {ph:8} {fmt(raw[ph])}\n  {'':8} {fmt(voted[ph])}")


if __name__ == "__main__":
    main()
