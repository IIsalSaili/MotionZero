"""Application : caméra -> points de la main -> machine à états -> souris/clavier.

  python -m motionzero               normal
  python -m motionzero --simulation  n'envoie rien à Windows (affiche seulement)

Pour arrêter : fermer la fenêtre d'aperçu (croix), à la souris ou en mode souris.
"""
import argparse
import logging
import os
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from .camera import OK, Camera
from .config import load_config
from .core import Core, Mode
from .hand import HandTracker
from .overlay import render
from .output import Controller, FakeBackend, SendInputBackend, primary_screen, set_dpi_aware
from .sounds import Sounds

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIN = "motionzero"
DETECT_MAX_FPS = 20          # plafond de détection (moins de charge)
STALE_S = 0.5                # sans image depuis 0,5 s : caméra considérée perdue


def main(argv=None):
    ap = argparse.ArgumentParser(prog="motionzero")
    ap.add_argument("--simulation", action="store_true", help="n'envoie rien a Windows")
    ap.add_argument("--voice", action="store_true", help="active les commandes vocales (micro)")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--duration", type=float, default=0, help="arret automatique apres N secondes (tests)")
    ap.add_argument("--screenshot", default="", help="enregistre la derniere image de l'appli (tests)")
    args = ap.parse_args(argv)

    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    logging.basicConfig(filename=os.path.join(ROOT, "logs", "motionzero.log"), level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    log = logging.getLogger("motionzero")

    set_dpi_aware()
    cfg = load_config(args.config)
    core = Core(cfg, primary_screen())
    tracker = HandTracker()
    backend = FakeBackend() if args.simulation else SendInputBackend()
    ctl = Controller(backend, cfg)
    sounds = Sounds(os.path.join(ROOT, "assets", "sounds"), cfg.sounds)
    # les DEUX mains sont détectées (demande de l'utilisateur) ; CPU mesuré ~7 % : marge suffisante
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "hand_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_hands=2))
    cam = Camera(cfg.camera_index, cfg.width, cfg.height).start()
    listener = None
    if args.voice:
        from .voice import VoiceListener, default_model_dir
        listener = VoiceListener(default_model_dir(ROOT)).start()
    # VS Code (micro de Claude, Entrée) : toujours envoyé pour de vrai, même en simulation,
    # sinon la dictée ne peut pas être essayée. Seules ces touches-là, et seulement vers VS Code.
    vscode_ctl = Controller(SendInputBackend(), cfg)
    log.info("demarrage (simulation=%s) camera=%s", args.simulation, cam.info)

    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)  # fenêtre simple : WINDOW_NORMAL donnait une image grise

    t0 = time.perf_counter()
    seq, last_ts, fps, frames, fps_t = 0, -1, 0.0, 0, t0
    last_detect, last_frame_t = 0.0, t0
    last_view = np.zeros((cfg.height, cfg.width, 3), np.uint8)
    pts = None
    try:
        while True:
            t = time.perf_counter()
            frame, new_seq = cam.read(seq)
            if frame is not None and t - last_detect >= 1.0 / DETECT_MAX_FPS:
                seq = new_seq
                last_detect = last_frame_t = t
                view = cv2.flip(frame, 1)
                ts = max(int((t - t0) * 1000), last_ts + 1)
                last_ts = ts
                rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
                res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                all_hands = [[(p.x, p.y) for p in h] for h in res.hand_landmarks]
                pts = tracker.update(all_hands, t)  # les deux mains suivies ; celle qui bouge agit
                acts = core.step(pts, t)
                frames += 1
                if t - fps_t >= 1.0:
                    fps, frames, fps_t = frames / (t - fps_t), 0, t
            elif t - last_frame_t > STALE_S:
                # caméra muette : on traite comme « main absente » (relâche tout, puis repos)
                view, pts = last_view.copy() // 3, None
                acts = core.step(None, t)
            else:
                view, acts = None, []
                if frame is not None:
                    time.sleep(0.005)  # image dispo mais plafond atteint : pas de boucle active

            if listener is not None:
                acts = acts + core.dictation_tick(t, listener.last_speech_t)
                for ev in listener.poll():
                    acts = acts + core.voice(ev.word, ev.t_end)
                    accepted = core.last_word and core.last_word[2]
                    log.info("voix %s (%.2f) %s", ev.word, ev.conf, "acceptee" if accepted else "ignoree (ecoute fermee)")
                    if ev.word == "iris" and accepted:
                        sounds.play("ECOUTE")
            acts = vscode_actions(acts, core, vscode_ctl, sounds, t)
            ctl.execute(acts, t)
            for a in acts:
                if a[0] == "mode":
                    sounds.play(a[1])
                    log.info("mode %s", a[1])
                elif a[0] == "scroll":
                    log.info("scroll %s", a[1])
                elif a[0] == "hotkey":
                    log.info("touches %s", "+".join(a[1]))
                elif a[0] in ("key", "click"):
                    sounds.play("CLIC")
                    log.info("%s %s (%s)", a[0], a[1], core.last_gesture[0] if core.last_gesture else "")

            if view is not None:
                if pts is not None or frame is not None:
                    last_view = view.copy()
                status = cam.status if t - last_frame_t <= STALE_S else (cam.status if cam.status != OK else "perdue")
                shown = render(view, core, tracker.tracks if pts is not None else [], fps, args.simulation,
                               status, tracker.active_id, voice_on=listener is not None)
                cv2.imshow(WIN, shown)
            # toujours pomper les messages Windows, image ou pas (sinon fenêtre fantôme « ne répond pas »)
            cv2.waitKey(1)
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break  # fenêtre fermée = STOP
            if args.duration and t - t0 >= args.duration:
                if args.screenshot and "shown" in locals():
                    cv2.imwrite(args.screenshot, shown)
                break
    finally:
        ctl.release_all()
        if listener is not None:
            listener.stop()
        cam.stop()
        landmarker.close()
        cv2.destroyAllWindows()
        log.info("arret (images rejetees=%d, reconnexions=%d)", cam.rejected, cam.reconnections)


def vscode_actions(acts, core, ctl, sounds, t):
    """Exécute les actions VS Code (« vscode_dictation », « vscode_keys ») ; renvoie les autres."""
    from .vscode import focus_and_send, toggle_claude_dictation

    def send(keys):
        ctl.execute([("hotkey", keys)], time.perf_counter())

    rest = []
    for a in acts:
        if a[0] == "vscode_dictation":
            err = toggle_claude_dictation(send)
            if not err and core.dictating:
                time.sleep(0.4)          # le micro de VS Code met un instant à démarrer
                sounds.play("PARLE")     # signal : tu peux parler
            elif not err:
                sounds.play("COUPE")     # micro coupé : dis « envoie » ou « annule »
        elif a[0] == "vscode_keys":
            err = focus_and_send(send, a[1])
        else:
            rest.append(a)
            continue
        if err:  # VS Code introuvable : on le dit, et on n'attend pas une dictée qui n'a pas démarré
            core.dictating = False
            core.confirm_until = -1e9
            core.last_gesture = (err, t)
    return rest


if __name__ == "__main__":
    main()
