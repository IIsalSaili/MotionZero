"""Image caméra de l'accueil : bandes de bord, mains, anneau d'immobilité, bulle, menu, panne de caméra.
Aucun texte d'aide ici : l'aide, l'état et les dernières commandes sont dessinés en Qt (accueil.py, ui.py)."""
import time

import cv2
import numpy as np

from .camera import OK
from .core import MENU_LABELS, Mode

WHITE, DIM, GREEN, YELLOW = (255, 255, 255), (110, 110, 110), (0, 220, 0), (0, 220, 255)
FLASH_S = 1.5


def _text(img, s, xy, scale=0.5, color=WHITE, thick=1):
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _px(img, p):
    h, w = img.shape[:2]
    return int(p[0] * w), int(p[1] * h)


def _blend_rect(img, x0, x1, color, alpha):
    roi = img[:, x0:x1]
    overlay = np.full_like(roi, color)
    cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, roi)


def render(frame, core, tracks, fps, simulation, cam_status, active_id=None, voice_on=False):
    now = time.perf_counter()
    cfg = core.cfg
    h, w = frame.shape[:2]
    cam = frame

    # souris pas encore armée : zone où amener la paume
    if core.mouse and not core.armed:
        ac = _px(cam, cfg.arm_center)
        cv2.circle(cam, ac, int(cfg.arm_radius * w), (0, 165, 255), 3)
        _text(cam, "MAIN AU CENTRE", (ac[0] - 75, ac[1] - int(cfg.arm_radius * w) - 10), 0.6, (0, 165, 255), 2)

    # mains : l'active en couleur, l'autre en gris
    for tr in tracks or []:
        is_active = tr["id"] == active_id
        color = YELLOW if is_active else DIM
        for p in tr["pts"]:
            cv2.circle(cam, _px(cam, p), 4 if is_active else 3, color, -1)

    # anneau d'immobilité / progression autour de la paume
    if core.palm is not None:
        c = _px(cam, core.palm)
        pr = core.progress()
        if pr:
            cv2.ellipse(cam, c, (34, 34), -90, 0, int(360 * pr[1]), GREEN, 5)
            _text(cam, pr[0], (c[0] - 50, c[1] + 54), 0.5, GREEN, 1)
        # menu à 4 directions
        if core.menu.is_open:
            mc = _px(cam, core.menu.center)
            r = 80  # écartement à l'affichage seulement (la sélection reste à menu_select)
            cv2.circle(cam, mc, int(cfg.menu_neutral * w), DIM, 1)
            spots = {"left": (-r, 0), "right": (r, 0), "up": (0, -r), "down": (0, r)}
            for key, (dx, dy) in spots.items():
                p = (mc[0] + dx, mc[1] + dy)
                hot = core.menu.hover == key
                cv2.circle(cam, p, 18, GREEN if hot else (70, 70, 70), -1)
                label = MENU_LABELS[key]
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                pos = {"left": (p[0] - 24 - tw, p[1] + th // 2), "right": (p[0] + 24, p[1] + th // 2),
                       "up": (p[0] - tw // 2, p[1] - 26), "down": (p[0] - tw // 2, p[1] + 26 + th)}[key]
                cv2.rectangle(cam, (pos[0] - 4, pos[1] - th - 4), (pos[0] + tw + 4, pos[1] + 4), (20, 20, 20), -1)
                _text(cam, label, pos, 0.5, GREEN if hot else WHITE, 1)
            left = max(0.0, cfg.menu_timeout_s - (now - core.menu.t0))
            _text(cam, f"{left:.1f} s", (mc[0] - 18, mc[1] + 5), 0.45, WHITE, 1)

    # confirmation d'action : un contour vert (le libellé est dans les dernières commandes de l'accueil)
    if core.last_gesture and now - core.last_gesture[1] < FLASH_S:
        cv2.rectangle(cam, (0, 0), (w - 1, h - 1), GREEN, 8)

    if cam_status != OK:
        cv2.rectangle(cam, (0, h // 2 - 40), (w, h // 2 + 40), (0, 0, 160), -1)
        _text(cam, f"CAMERA {cam_status.upper()}", (20, h // 2 + 12), 1.1, WHITE, 3)

    # l'état (écoute, dictée), l'aide et les dernières commandes sont sur la page d'accueil (accueil.py)
    return cam
