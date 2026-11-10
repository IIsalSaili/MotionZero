"""Enregistrement guidé des poses, pensé pour une main douloureuse. Aucune image n'est gardée.

  python tools/record_poses.py recordings/poses_calib.jsonl

- 4 poses seulement, dans l'orientation naturelle de la main, coude posé, sans serrer.
- Démarre seulement quand une main est vue 2 s de suite. La fenêtre passe au premier plan.
- 5 s par pose, avec une pause bras posé entre chaque pose.
- Une pose fait mal ? Retirez simplement la main : la pose est passée, rien n'est exigé.
- Pour chaque image : points 2D, points 3D (« monde », en mètres), main gauche ou droite,
  et l'avis du modèle de gestes de Google (Closed_Fist, Open_Palm, Pointing_Up…) pour comparer.
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

from motionzero.camera import OK, Camera

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "models", "gesture_recognizer.task")
REST = ("pause", "Posez le bras, detendez la main", 4)
# (code, consigne à l'écran, durée en s). Sans accents : l'écran OpenCV ne les affiche pas.
PHASES = [
    ("prepare", "C'est parti. Gardez le coude pose", 3),
    ("open", "MAIN OUVERTE DETENDUE (sans ecarter le pouce)", 5), REST,
    ("closed", "MAIN FERMEE SANS SERRER", 5), REST,
    ("point", "INDEX POINTE, autres doigts souples", 5), REST,
    ("pinch", "PINCEMENT LEGER pouce-index, 2 ou 3 fois", 6), REST,
    ("none", "Retirez la main", 3),
]
# Session courte : l'index tourné vers la caméra (python tools/record_poses.py sortie.jsonl index_face)
SESSIONS = {"index_face": [
    ("prepare", "C'est parti. Gardez le coude pose", 3),
    ("point_face", "INDEX POINTE VERS LA CAMERA (si c'est confortable)", 6), REST,
    ("point", "INDEX POINTE vers le haut, comme avant", 5), REST,
    ("point_face", "Encore : INDEX VERS LA CAMERA", 6), REST,
    ("none", "Retirez la main", 3),
]}
WIN = "motionzero - enregistrement des poses"
HINT = "Si ca fait mal : retirez la main, la pose est passee."
READY_S = 2.0   # main vue 2 s de suite = prêt : l'enregistrement démarre seulement là


def bring_to_front(title):
    """Met la fenêtre au premier plan (Windows refuse sauf juste après une touche : on relâche Alt)."""
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, title)
    if not hwnd:
        return False
    u.keybd_event(0x12, 0, 0x2, 0)   # Alt relâché : autorise SetForegroundWindow
    u.ShowWindow(hwnd, 9)            # SW_RESTORE
    u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x3)   # au-dessus de tout (sans bouger ni redimensionner)
    u.SetForegroundWindow(hwnd)
    return True


def current_phase(t):
    acc = 0
    for ph in PHASES:
        if t < acc + ph[2]:
            return ph, acc + ph[2] - t
        acc += ph[2]
    return None, 0


def hands_of(res):
    """Toutes les mains vues : 2D, 3D monde, gauche/droite, geste reconnu par le modèle de Google."""
    out = []
    for i, lms in enumerate(res.hand_landmarks):
        world = res.hand_world_landmarks[i] if i < len(res.hand_world_landmarks) else []
        side = res.handedness[i][0] if i < len(res.handedness) and res.handedness[i] else None
        gest = res.gestures[i][0] if i < len(res.gestures) and res.gestures[i] else None
        out.append({
            "pts": [[round(p.x, 4), round(p.y, 4)] for p in lms],
            "z": [round(p.z, 4) for p in lms],
            "world": [[round(p.x, 5), round(p.y, 5), round(p.z, 5)] for p in world],
            "hand": side.category_name if side else None,
            "hand_score": round(side.score, 3) if side else None,
            "gesture": gest.category_name if gest else None,
            "gesture_score": round(gest.score, 3) if gest else None,
        })
    return out


def draw(view, phase, remaining, hands):
    h, w = view.shape[:2]
    for hd in hands:
        for x, y in hd["pts"]:
            cv2.circle(view, (int(x * w), int(y * h)), 3, (0, 200, 255), -1)
    rest = phase[0] in ("pause", "wait")
    cv2.rectangle(view, (0, 0), (w, 70), (90, 90, 90) if rest else (216, 78, 29), -1)
    cv2.putText(view, phase[1], (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    status = "" if phase[0] == "wait" else f"{int(remaining) + 1} s" + (
        "" if hands or rest else "   aucune main (pose passee)")
    cv2.putText(view, status, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.rectangle(view, (0, h - 30), (w, h), (0, 0, 0), -1)
    cv2.putText(view, HINT, (12, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def main():
    global PHASES
    out_path = sys.argv[1]
    if len(sys.argv) > 2:
        PHASES = SESSIONS[sys.argv[2]]
    rec = vision.GestureRecognizer.create_from_options(vision.GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.VIDEO, num_hands=2))
    cam = Camera().start()
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    t0 = time.perf_counter()
    seq, last_ts, n, last_frame_t = 0, -1, 0, t0
    view = np.zeros((480, 640, 3), np.uint8)
    cv2.imshow(WIN, view)
    cv2.waitKey(1)
    front = bring_to_front(WIN)
    ready_since, started = None, None   # attente : rien n'est enregistré tant que la main n'est pas là
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            while True:
                now = time.perf_counter()
                if not front and now - t0 < 5:
                    front = bring_to_front(WIN)
                if started is None:
                    frame, new_seq = cam.read(seq)
                    if frame is not None:
                        seq, last_frame_t = new_seq, now
                        view = cv2.flip(frame, 1)
                        ts = max(int((now - t0) * 1000), last_ts + 1)
                        last_ts = ts
                        res = rec.recognize_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                               data=cv2.cvtColor(view, cv2.COLOR_BGR2RGB)), ts)
                        seen = bool(res.hand_landmarks)
                        ready_since = (ready_since or now) if seen else None
                        left = READY_S - (now - ready_since) if ready_since else READY_S
                        msg = ("Prete ? Gardez la main... " + f"{max(left, 0):.0f}" if seen
                               else "Montrez la main quand vous etes pret")
                        draw(view, ("wait", msg, 0), 0, hands_of(res))
                        cv2.imshow(WIN, view)
                        if ready_since and now - ready_since >= READY_S:
                            started = now
                    cv2.waitKey(1)
                    if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                        break
                    continue
                t = now - started
                phase, remaining = current_phase(t)
                if phase is None:
                    break
                frame, new_seq = cam.read(seq)
                if frame is not None:
                    seq, last_frame_t = new_seq, time.perf_counter()
                    view = cv2.flip(frame, 1)
                    ts = max(int((now - t0) * 1000), last_ts + 1)
                    last_ts = ts
                    res = rec.recognize_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(view, cv2.COLOR_BGR2RGB)), ts)
                    hands = hands_of(res)
                    fh.write(json.dumps({"t": round(t, 4), "phase": phase[0], "hands": hands}) + "\n")
                    n += 1
                    draw(view, phase, remaining, hands)
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
        rec.close()
        cv2.destroyAllWindows()
    print(f"{n} images enregistrees dans {out_path} (rejetees: {cam.rejected}, reconnexions: {cam.reconnections})")


if __name__ == "__main__":
    main()
