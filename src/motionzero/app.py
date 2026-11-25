"""Application : caméra -> points de la main -> machine à états -> souris/clavier.

  python -m motionzero               normal
  python -m motionzero --simulation  n'envoie rien à Windows (affiche seulement)

Pour arrêter : uniquement le petit bouton STOP en bas à droite (clic, ou main tenue dessus).
L'interface est en Qt (fil principal) ; caméra, MediaPipe et Core tournent dans un fil à part.
"""
import logging
import time
from collections import deque

import cv2
import numpy as np


from .app_outils import (CONFIRM_WORDS, CONV_FILE, ERROR_NOTICE, POINTER_FILE, QUIET_FILE, QUOTA_FILE, VOLUME_FILE, VOLUME_STEPS, cam_down, cand_panel, detect_period, drain, last_tab, lower_priority, next_quiet, next_volume, note_error, pick_toast, plan_card, read_conversation, read_pointer, read_quiet, read_volume, reminder_shown, top_shown, watch_engine, write_pointer)  # noqa: F401
from .app_actions import (bot_absent, bot_events, discord_actions, discord_command, discord_spoken, open_actions, question_actions, type_actions, vscode_actions)  # noqa: F401
from .app_main import (DETECT_MAX_FPS, EXIT_GUARD_S, HOME_PERIOD_S, IDLE_AFTER_S, IDLE_DETECT_FPS, ROOT, STALE_S, WIN, force_exit, main)  # noqa: F401
from .app_detection import DetectionMixin
from .app_ecoute import EcouteMixin
from .app_affichage import AffichageMixin

_log = logging.getLogger("motionzero")


class Engine(DetectionMixin, EcouteMixin, AffichageMixin):
    """Boucle principale (fil « moteur ») : caméra -> détection -> Core -> actions -> affichage.
    Un tour = tick() : détecter, écouter, faire, montrer. `d` porte les services créés par main()
    (caméra, Core, voix, bot, rappels, interface…) ; l'état propre à la boucle vit ici."""

    def __init__(self, d):
        self.d = d
        self.t0 = time.perf_counter()
        self.seq, self.last_ts, self.fps, self.frames, self.fps_t = 0, -1, 0.0, 0, self.t0
        self.last_detect, self.last_frame_t = 0.0, self.t0
        self.last_view = np.zeros((d.cfg.height, d.cfg.width, 3), np.uint8)
        self.pts = None
        self.face_lost = True                 # souris à la tête : visage vu à la dernière détection ?
        self.last_level_log = 0.0
        self.last_rej_seen = self.last_fail_seen = None
        self.chrome_check_t = 0.0
        self.quiet_check_t = -1e9
        self.mic_check_t = -1e9
        self.quiet_choice = getattr(d, "quiet_choice", "auto")
        self.last_hand_t = self.t0
        self.errors = deque(maxlen=20)
        self.shown = None                     # dernière image dessinée (capture des tests)
        self.frame_seen = False               # une image est arrivée à ce tour
        self.home_t = self.guard_t = -1e9      # page d'accueil : dernière mise à jour, dernier regard au gardien
        self.guard_on = False
        self.speed_log_t = -1e9                # journal des vitesses de la tête

    def run(self):
        d = self.d
        try:
            while not d.stop.is_set():
                try:
                    if self.tick():
                        break
                except Exception:
                    # une erreur dans un tour de boucle ne doit jamais arrêter motionzero : on la note,
                    # on relâche tout ce qui est tenu, et on continue (l'utilisateur en dépend)
                    self.errors.append(time.perf_counter())
                    _log.exception("erreur dans la boucle principale (on continue)")
                    note_error("boucle")
                    d.ctl.release_all()
                    if len(self.errors) >= 20 and self.errors[-1] - self.errors[-20] < 10.0:
                        raise   # erreur en boucle : inutile d'insister
                    time.sleep(0.05)
        finally:
            d.ctl.release_all()
            if d.listener is not None:
                d.listener.stop()
            if getattr(d, "traducteur", None) is not None:
                d.traducteur.stop()
            d.cam.stop()
            d.landmarker.close()
            if d.faces["lm"] is not None:
                d.faces["lm"].close()
            _log.info("arret (images rejetees=%d, reconnexions=%d)", d.cam.rejected, d.cam.reconnections)

    def tick(self):
        """Un tour de boucle. Renvoie True quand la durée de test (--duration) est écoulée."""
        d = self.d
        t = time.perf_counter()
        d.live["beat"] = t                    # surveillé : voir watch_engine et garde.run_beat
        view, acts = self.detect(t)
        acts = acts + self.background(t)
        acts = acts + self.listen(t)
        acts = self.resolve(acts, t)
        d.ctl.execute(acts, t)
        self.after(acts)
        if view is not None:
            self.publish(view, t)
        else:
            time.sleep(0.002)                 # rien de neuf : ne pas monopoliser le processeur
        if d.args.duration and t - self.t0 >= d.args.duration:
            if d.args.screenshot and self.shown is not None:
                cv2.imwrite(d.args.screenshot, self.shown)
            return True
        return False


if __name__ == "__main__":
    main()
