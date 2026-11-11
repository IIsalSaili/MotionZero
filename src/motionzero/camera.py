"""Capture webcam robuste.

- Ouverte UNE seule fois, en DirectShow, format MJPG compressé (moins de débit USB que YUY2).
  Le format est demandé AVANT la taille, sinon il est ignoré.
- Un thread lit les images et garde seulement la dernière (copiée : jamais partagée avec la capture).
- Les images corrompues (neige, image uniforme) sont jetées.
- Si plus aucune image valide pendant 2 s : la caméra est fermée puis rouverte automatiquement.
- Verrou système : deux programmes ne peuvent pas ouvrir la caméra en même temps.
"""
import ctypes
import logging
import sys
import threading
import time

import cv2
import numpy as np

log = logging.getLogger("motionzero.camera")

OK, LOST, RECONNECTING, STOPPED = "ok", "perdue", "reconnexion", "arretee"


def frame_is_valid(frame, max_grain_ratio=0.7, min_grain=8.0, min_std=2.0):
    """Faux si l'image ressemble à de la neige ou est uniforme.

    Neige = pixels voisins sans rapport entre eux : l'écart moyen entre voisins approche l'écart-type de la bande
    (rapport ~1). Une vraie image, même très texturée, a des voisins proches (rapport ~0,25).
    L'ancien critère (écart entre voisins > 15) rejetait de vraies images en plein jour : mur crépi et rideau à
    motifs mesurés à 16 -> la caméra était crue en panne et redémarrée en boucle."""
    if frame is None or frame.ndim != 3 or frame.shape[0] < 8:
        return False
    gray = cv2.cvtColor(frame[::4, ::4], cv2.COLOR_BGR2GRAY).astype(np.int16)
    if gray.std() < min_std:
        return False
    for band in np.array_split(gray, 4, axis=0):
        grain = np.abs(np.diff(band, axis=1)).mean()
        if grain > min_grain and grain > max_grain_ratio * band.std():
            return False
    return True


class _SingleInstance:
    """Mutex Windows nommé : empêche deux ouvertures simultanées de la caméra."""

    def __init__(self, name="Local\\motionzero_camera"):
        self.handle = None
        if sys.platform == "win32":
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.k32 = k32
            self.handle = k32.CreateMutexW(None, False, name)
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                k32.CloseHandle(self.handle)
                self.handle = None
                raise RuntimeError("la camera est deja utilisee par un autre programme motionzero")

    def release(self):
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


class Camera:
    def __init__(self, index=0, width=640, height=480, fps=30, lost_after_s=2.0, warmup_frames=10):
        self.index, self.width, self.height, self.fps = index, width, height, fps
        self.lost_after_s = lost_after_s
        self.warmup_frames = warmup_frames
        self.cap = None
        self.frame = None
        self.frame_t = 0.0
        self.seq = 0
        self.status = STOPPED
        self.rejected = 0
        self.reconnections = 0
        self.info = {}
        self.running = False
        self.cond = threading.Condition()
        self.thread = None
        self.lock = None

    # --- ouverture ---------------------------------------------------------
    def _open(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        # format compressé APRÈS la taille et la cadence : mesuré sur la webcam UGREEN, demandé avant il
        # n'est pas appliqué (YUY2 brut, 4 images/s en 1080p) ; demandé en dernier : MJPG à 29 images/s
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        self.info = {"fourcc": "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)),
                     "taille": (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))),
                     "fps": cap.get(cv2.CAP_PROP_FPS)}
        log.info("camera ouverte %s", self.info)
        for _ in range(self.warmup_frames):  # premières images souvent sombres ou vertes
            cap.read()
        return cap

    def start(self):
        self.lock = _SingleInstance()
        self.cap = self._open()
        if self.cap is None:
            self.lock.release()
            raise RuntimeError(f"webcam {self.index} introuvable")
        self.running = True
        self.status = OK
        self.thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self.thread.start()
        return self

    # --- lecture -----------------------------------------------------------
    def _run(self):
        last_good = time.perf_counter()
        while self.running:
            try:
                ok, frame = self.cap.read() if self.cap is not None else (False, None)
                now = time.perf_counter()
                if ok and frame_is_valid(frame):
                    with self.cond:
                        self.frame = frame.copy()
                        self.frame_t = now
                        self.seq += 1
                        self.status = OK
                        self.cond.notify_all()
                    last_good = now
                    continue
                if ok:
                    self.rejected += 1
                if now - last_good > self.lost_after_s:
                    self._reconnect()
                    last_good = time.perf_counter()
                else:
                    time.sleep(0.02)  # jamais de boucle active à 100 %
            except Exception:
                log.exception("erreur de capture")
                time.sleep(0.2)

    def _reconnect(self):
        self.status = RECONNECTING
        self.reconnections += 1
        log.warning("camera perdue : reconnexion n°%d", self.reconnections)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        time.sleep(1.0)
        if self.running:
            self.cap = self._open()
            if self.cap is None:
                self.status = LOST

    def read(self, last_seq, timeout=0.05):
        """Renvoie (image, seq) si une image plus récente que last_seq existe, sinon (None, last_seq).
        Timeout court : la boucle d'affichage n'est jamais bloquée."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq or not self.running, timeout)
            if self.seq == last_seq:
                return None, last_seq
            return self.frame, self.seq

    # --- arrêt -------------------------------------------------------------
    def stop(self):
        self.running = False
        with self.cond:
            self.cond.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                # ne jamais libérer la caméra pendant une lecture en cours dans l'autre thread
                log.error("thread camera bloque : liberation laissee a la fin du processus")
                return
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.lock is not None:
            self.lock.release()
        self.status = STOPPED
