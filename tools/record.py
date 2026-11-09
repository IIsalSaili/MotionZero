"""Enregistrement guidé des points de la main (aucune image enregistrée). Main gauche ou droite.

  python tools/record.py sortie.jsonl

Utilise la même capture robuste que l'appli (MJPG, images corrompues jetées, reconnexion).
Fermer la fenêtre arrête l'enregistrement.
"""
import json
import os
import sys
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from motionzero.camera import OK, Camera

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHASES = [
    ("prepare", "Prepare-toi : une main devant la camera", 5),
    ("open", "PAUME OUVERTE, immobile", 5),
    ("point", "INDEX POINTE (autres doigts replies)", 5),
    ("pinch", "PINCE pouce-index 3 fois, doucement", 8),
    ("fist", "POING FERME", 5),
    ("swipe", "Main ouverte : BALAYE 2 fois de droite a gauche", 8),
    ("rest", "Repos : baisse la main", 4),
]
WIN = "motionzero - enregistrement"


def current_phase(t):
    acc = 0
    for ph in PHASES:
        if t < acc + ph[2]:
            return ph, acc + ph[2] - t
        acc += ph[2]
    return None, 0


def main():
    out_path = sys.argv[1]
    lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "hand_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_hands=1))
    cam = Camera().start()
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    t0 = time.perf_counter()
    seq, last_ts, n, last_frame_t = 0, -1, 0, t0
    view = np.zeros((480, 640, 3), np.uint8)
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            while True:
                t = time.perf_counter() - t0
                phase, remaining = current_phase(t)
                if phase is None:
                    break
                frame, new_seq = cam.read(seq)
                if frame is not None:
                    seq, last_frame_t = new_seq, time.perf_counter()
                    view = cv2.flip(frame, 1)
                    ts = max(int(t * 1000), last_ts + 1)
                    last_ts = ts
                    res = lm.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(view, cv2.COLOR_BGR2RGB)), ts)
                    pts = [(p.x, p.y) for p in res.hand_landmarks[0]] if res.hand_landmarks else None
                    fh.write(json.dumps({"t": round(t, 4), "phase": phase[0],
                                         "pts": [[round(x, 4), round(y, 4)] for x, y in pts] if pts else None}) + "\n")
                    n += 1
                    h, w = view.shape[:2]
                    if pts:
                        for x, y in pts:
                            cv2.circle(view, (int(x * w), int(y * h)), 3, (0, 200, 255), -1)
                    cv2.rectangle(view, (0, 0), (w, 64), (216, 78, 29), -1)
                    cv2.putText(view, phase[1], (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    cv2.putText(view, f"{int(remaining) + 1} s" + ("" if pts else "   AUCUNE MAIN"), (12, 56),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                    cv2.imshow(WIN, view)
                elif time.perf_counter() - last_frame_t > 0.5:
                    lost = view // 3
                    cv2.putText(lost, f"CAMERA {cam.status.upper() if cam.status != OK else 'PERDUE'}", (20, 240),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
                    cv2.imshow(WIN, lost)
                cv2.waitKey(1)  # toujours, image ou pas
                if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        cam.stop()
        lm.close()
        cv2.destroyAllWindows()
    print(f"{n} images enregistrees dans {out_path} (rejetees: {cam.rejected}, reconnexions: {cam.reconnections}, "
          f"format: {cam.info})")


if __name__ == "__main__":
    main()
