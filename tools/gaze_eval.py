"""Mesure de la précision du regard à partir d'un enregistrement de tools/gaze_record.py.

  python tools/gaze_eval.py recordings/regard_1.jsonl

Calibration : régression (polynôme de degré 2, ridge) des caractéristiques des yeux et de la tête vers
l'écran, apprise sur les 9 points de calibration. Erreur mesurée sur les 16 points de test, jamais vus.
On ne garde que la fin de chaque point (après 0,6 s), le temps que l'œil s'y pose.
"""
import json
import sys

import numpy as np

SETTLE_S = 0.6


def eye_feats(f, iris, inner, outer, top, bottom):
    c = np.mean([f[str(i)][:2] for i in iris], axis=0)
    a, b = np.array(f[str(inner)][:2]), np.array(f[str(outer)][:2])
    t, d = np.array(f[str(top)][:2]), np.array(f[str(bottom)][:2])
    ax = b - a
    u = np.dot(c - a, ax) / np.dot(ax, ax)                      # position horizontale dans l'œil (0..1)
    v = np.dot(c - t, d - t) / max(np.dot(d - t, d - t), 1e-9)   # position verticale entre les paupières
    return [u, v]


def features(rec):
    f = rec["face"]
    left = eye_feats(f, range(468, 473), 33, 133, 159, 145)
    right = eye_feats(f, range(473, 478), 362, 263, 386, 374)
    feats = left + right
    if rec.get("pose"):
        m = np.array(rec["pose"])
        r = m[:3, :3]
        yaw = np.arctan2(-r[2, 0], np.hypot(r[0, 0], r[1, 0]))
        pitch = np.arctan2(r[2, 1], r[2, 2])
        feats += [yaw, pitch, m[0, 3] / 10, m[1, 3] / 10, m[2, 3] / 10]
    return feats


def poly2(x):
    x = np.asarray(x)
    cols = [np.ones(len(x))] + [x[:, i] for i in range(x.shape[1])]
    cols += [x[:, i] * x[:, j] for i in range(x.shape[1]) for j in range(i, x.shape[1])]
    return np.stack(cols, axis=1)


def fit(X, Y, lam):
    P = poly2(X)
    mu, sd = P[:, 1:].mean(0), P[:, 1:].std(0) + 1e-9
    P[:, 1:] = (P[:, 1:] - mu) / sd
    W = np.linalg.solve(P.T @ P + lam * np.eye(P.shape[1]), P.T @ Y)
    return lambda Xn: np.c_[np.ones(len(Xn)), (poly2(Xn)[:, 1:] - mu) / sd] @ W


def main():
    lines = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    head, rows = lines[0], [r for r in lines[1:] if r.get("face") and r["in"] >= SETTLE_S]
    seen = sum(1 for r in lines[1:] if r.get("face")) / max(1, len(lines) - 1)
    print(f"écran {head['screen']}, visage détecté sur {100 * seen:.0f} % des images")
    for name, use_pose in (("yeux seuls", False), ("yeux + pose de la tête", True)):
        cal = [r for r in rows if r["phase"] == "calib"]
        tst = [r for r in rows if r["phase"] == "test"]
        cut = 4 if use_pose else 4
        fx = (lambda r: features(r)) if use_pose else (lambda r: features(r)[:cut])
        Xc, Yc = np.array([fx(r) for r in cal]), np.array([[r["x"], r["y"]] for r in cal], float)
        best = None
        for lam in (0.1, 1, 10, 100):
            model = fit(Xc, Yc, lam)
            per_target = {}
            for r in tst:
                per_target.setdefault(r["k"], ([], (r["x"], r["y"])))[0].append(fx(r))
            err_t = [np.hypot(*(model(np.array(v)).mean(0) - np.array(xy))) for v, xy in per_target.values()]
            P = model(np.array([fx(r) for r in tst]))
            err_f = np.hypot(*(P - np.array([[r["x"], r["y"]] for r in tst])).T)
            res = (np.median(err_t), np.percentile(err_t, 90), np.median(err_f), lam)
            if best is None or res[0] < best[0]:
                best = res
        print(f"{name:24} : erreur par point (fixation moyennée) médiane {best[0]:.0f} px, 90e centile {best[1]:.0f} px"
              f" | image par image médiane {best[2]:.0f} px  (régularisation {best[3]})")


if __name__ == "__main__":
    main()
