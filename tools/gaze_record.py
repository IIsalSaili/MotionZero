"""Enregistrement pour mesurer la précision du regard par webcam. Aucune image n'est gardée.

  python tools/gaze_record.py recordings/regard_1.jsonl

Plein écran noir : un point apparaît à 25 endroits (9 de calibration puis 16 de test), 1,5 s chacun.
Il suffit de regarder le point, sans bouger la tête. Pour chaque image on garde seulement les points
utiles du visage (iris, coins et paupières des yeux) et la pose de la tête.
"""
import ctypes
import json
import os
import sys
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from motionzero.camera import Camera
from record_poses import bring_to_front

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = "motionzero - mesure du regard"
KEEP = list(range(468, 478)) + [33, 133, 159, 145, 362, 263, 386, 374, 1, 6]   # iris, yeux, nez
DWELL_S, COUNTDOWN_S = 1.5, 5.0


def targets(w, h):
    """9 points de calibration (grille 3x3, marge 10 %), puis 16 de test (grille 4x4 décalée)."""
    mx, my = 0.1 * w, 0.1 * h
    calib = [(mx + i * (w - 2 * mx) / 2, my + j * (h - 2 * my) / 2) for j in range(3) for i in range(3)]
    test = [(0.15 * w + i * 0.7 * w / 3, 0.17 * h + j * 0.66 * h / 3) for j in range(4) for i in range(4)]
    rng = np.random.default_rng(7)
    test = [test[k] for k in rng.permutation(len(test))]
    return [("calib", x, y) for x, y in calib] + [("test", x, y) for x, y in test]


def main():
    out_path = sys.argv[1]
    ctypes.windll.user32.SetProcessDPIAware()
    w, h = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    fl = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1, output_facial_transformation_matrixes=True))
    cam = Camera().start()
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    blank = np.zeros((h, w, 3), np.uint8)
    cv2.imshow(WIN, blank)
    cv2.waitKey(1)
    bring_to_front(WIN)
    plan = targets(w, h)
    t0 = time.perf_counter()
    seq, last_ts, n = 0, -1, 0
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"screen": [w, h], "dwell_s": DWELL_S}) + "\n")
            while True:
                now = time.perf_counter() - t0
                img = blank.copy()
                if now < COUNTDOWN_S:
                    msg = f"Regardez le point blanc a chaque fois, sans bouger la tete. Debut dans {int(COUNTDOWN_S - now) + 1}"
                    cv2.putText(img, msg, (w // 2 - 620, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                    k = None
                else:
                    k = int((now - COUNTDOWN_S) // DWELL_S)
                    if k >= len(plan):
                        break
                    phase, x, y = plan[k]
                    cv2.circle(img, (int(x), int(y)), 14, (255, 255, 255), -1)
                    cv2.circle(img, (int(x), int(y)), 3, (0, 0, 0), -1)
                    cv2.putText(img, f"{k + 1} / {len(plan)}", (30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (120, 120, 120), 2)
                frame, new_seq = cam.read(seq)
                if frame is not None and k is not None:
                    seq = new_seq
                    view = cv2.flip(frame, 1)
                    ts = max(int(now * 1000), last_ts + 1)
                    last_ts = ts
                    res = fl.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(view, cv2.COLOR_BGR2RGB)), ts)
                    rec = {"t": round(now, 3), "k": k, "phase": phase, "x": round(x), "y": round(y),
                           "in": round(now - COUNTDOWN_S - k * DWELL_S, 3), "face": None}
                    if res.face_landmarks:
                        lm = res.face_landmarks[0]
                        rec["face"] = {str(i): [round(lm[i].x, 5), round(lm[i].y, 5), round(lm[i].z, 5)] for i in KEEP}
                        if res.facial_transformation_matrixes:
                            rec["pose"] = np.round(np.array(res.facial_transformation_matrixes[0]), 4).tolist()
                    fh.write(json.dumps(rec) + "\n")
                    n += 1
                elif frame is not None:
                    seq = new_seq
                cv2.imshow(WIN, img)
                cv2.waitKey(1)
    finally:
        cam.stop()
        fl.close()
        cv2.destroyAllWindows()
    print(f"{n} images enregistrees dans {out_path}")


if __name__ == "__main__":
    main()
