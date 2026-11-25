"""Application : caméra -> points de la main -> machine à états -> souris/clavier : méthodes de Engine (DetectionMixin, découpé de app.py, #52)."""
import logging
import time

import cv2
import mediapipe as mp

from .core import Mode

from .app_outils import (CONFIRM_WORDS, CONV_FILE, ERROR_NOTICE, POINTER_FILE, QUIET_FILE, QUOTA_FILE, VOLUME_FILE, VOLUME_STEPS, cam_down, cand_panel, detect_period, drain, last_tab, lower_priority, next_quiet, next_volume, note_error, pick_toast, plan_card, read_conversation, read_pointer, read_quiet, read_volume, reminder_shown, top_shown, watch_engine, write_pointer)  # noqa: F401
from .app_actions import (bot_absent, bot_events, discord_actions, discord_command, discord_spoken, open_actions, question_actions, type_actions, vscode_actions)  # noqa: F401

from .app_main import STALE_S

_log = logging.getLogger("motionzero")


class DetectionMixin:

    # --- 1. caméra et détection ---
    def _count_frame(self, t):
        self.frames += 1
        if t - self.fps_t >= 1.0:
            self.fps, self.frames, self.fps_t = self.frames / (t - self.fps_t), 0, t

    def _timestamp(self, t):
        self.last_ts = max(int((t - self.t0) * 1000), self.last_ts + 1)
        return self.last_ts

    def detect(self, t):
        """(image à montrer ou None, actions de la main / de la tête)."""
        d, core = self.d, self.d.core
        frame, new_seq = d.cam.read(self.seq)
        self.frame_seen = frame is not None
        disabled = core.mode == Mode.DISABLED
        period = detect_period(disabled, self.last_hand_t, t)
        d.live["detect_hz"] = 0 if disabled else 1.0 / detect_period(False, self.last_hand_t, t)
        if frame is not None and t - self.last_detect >= period:
            self.seq = new_seq
            self.last_detect = self.last_frame_t = t
            view = cv2.flip(frame, 1)
            if not disabled and core.pointer == "tete":
                return view, self._detect_head(view, t)
            return view, self._detect_hands(view, t, disabled)
        if t - self.last_frame_t > STALE_S + period:
            # caméra muette : on traite comme « main absente » (relâche tout, puis repos)
            self.pts = None
            return self.last_view.copy() // 3, core.step(None, t)
        if frame is not None:
            # image dispo mais plafond atteint : on dort jusqu'à la prochaine détection
            # (au plus 20 ms, pour que la voix reste réactive)
            time.sleep(min(max(self.last_detect + period - t, 0.005), 0.02))
        return None, []

    def _detect_head(self, view, t):
        """Souris à la tête : seul le détecteur de visage tourne (pas de double charge)."""
        ts = self._timestamp(t)
        rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
        try:
            fres = self.d.face_landmarker().detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            lms = [(p.x, p.y) for p in fres.face_landmarks[0]] if fres.face_landmarks else None
            mats = fres.facial_transformation_matrixes
            matrix = mats[0] if lms is not None and mats else None
        except Exception:
            _log.exception("detection du visage")
            lms = matrix = None
        self.face_lost = lms is None
        if lms is not None:
            self.last_hand_t = t
        self.pts = None
        self._count_frame(t)
        return self.d.core.step_head(lms, t, matrix)

    def _detect_hands(self, view, t, disabled):
        all_hands, world_hands = [], []
        if not disabled:                      # en pause, la main ne sert à rien : pas de MediaPipe
            ts = self._timestamp(t)
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            res = self.d.landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            all_hands = [[(p.x, p.y) for p in h] for h in res.hand_landmarks]
            world_hands = res.hand_world_landmarks
        self.pts = self.d.tracker.update(all_hands, t)   # les deux mains suivies ; celle qui bouge agit
        if all_hands:
            self.last_hand_t = t
        world = None                          # la même main en 3D
        for j, h in enumerate(all_hands):
            if h is self.pts and j < len(world_hands):
                world = [(p.x, p.y, p.z) for p in world_hands[j]]
        self._count_frame(t)
        return self.d.core.step(self.pts, t, world)
