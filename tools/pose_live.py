"""Test en direct de la reconnaissance des poses (angles 3D réglés sur l'utilisateur). Rien n'est enregistré.

  python tools/pose_live.py [durée_en_s]      (60 s par défaut, puis la fenêtre se ferme seule)

Affiche en grand la pose retenue (après vote), et en petit la pose image par image.
"""
import os
import sys
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from motionzero.camera import Camera
from motionzero.poses import LABELS, UNSURE, PoseVoter, classify, flexion, load_centroids
from record_poses import bring_to_front

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = "motionzero - test des poses"
COLORS = {"open": (80, 180, 60), "closed": (40, 40, 220), "point": (220, 140, 30), UNSURE: (110, 110, 110)}


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    cents = load_centroids(os.path.join(ROOT, "calibration", "poses.json"))
    lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "hand_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_hands=1))
    cam = Camera().start()
    voter = PoseVoter()
    view = np.zeros((480, 640, 3), np.uint8)
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(WIN, view)
    cv2.waitKey(1)
    front = bring_to_front(WIN)
    t0 = time.perf_counter()
    seq, last_ts = 0, -1
    try:
        while True:
            now = time.perf_counter()
            left = duration - (now - t0)
            if left <= 0:
                break
            if not front and now - t0 < 5:
                front = bring_to_front(WIN)
            frame, new_seq = cam.read(seq)
            if frame is not None:
                seq = new_seq
                view = cv2.flip(frame, 1)
                ts = max(int((now - t0) * 1000), last_ts + 1)
                last_ts = ts
                res = lm.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(view, cv2.COLOR_BGR2RGB)), ts)
                h, w = view.shape[:2]
                if res.hand_world_landmarks:
                    world = [(p.x, p.y, p.z) for p in res.hand_world_landmarks[0]]
                    f = flexion(world)
                    raw, d, ratio = classify(f, cents)
                    stable = voter.update(raw)
                    for p in res.hand_landmarks[0]:
                        cv2.circle(view, (int(p.x * w), int(p.y * h)), 3, (0, 200, 255), -1)
                    detail = f"image: {LABELS[raw]}  ecart {d:.1f}  doigts " + " ".join(f"{x:.0f}" for x in f)
                else:
                    voter.reset()
                    stable, detail = UNSURE, "aucune main"
                cv2.rectangle(view, (0, 0), (w, 80), COLORS[stable], -1)
                cv2.putText(view, LABELS[stable], (16, 56), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 4)
                cv2.rectangle(view, (0, h - 54), (w, h), (0, 0, 0), -1)
                cv2.putText(view, detail, (10, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(view, f"Fermeture automatique dans {int(left)} s", (10, h - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                cv2.imshow(WIN, view)
            cv2.waitKey(1)
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cam.stop()
        lm.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
