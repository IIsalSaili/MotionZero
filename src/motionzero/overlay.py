"""Affichage (gestes v2) : image caméra + bandes de bord + anneau d'immobilité + bulle + menu + panneau d'aide."""
import time

import cv2
import numpy as np

from .camera import OK
from .core import MENU_LABELS, Mode

PANEL_W = 340
WHITE, DIM, GREEN, YELLOW = (255, 255, 255), (110, 110, 110), (0, 220, 0), (0, 220, 255)
MODE_COLORS = {Mode.NEUTRAL: (90, 90, 90), Mode.READING: (216, 78, 29), Mode.MOUSE: (12, 65, 194), Mode.DISABLED: (60, 60, 60)}  # BGR
FLASH_S = 1.5

HELP = {
    Mode.NEUTRAL: [
        "NEUTRE : la main ne fait rien",
        "IRIS LECTURE > pages a la main",
        "IRIS SOURIS  > curseur a la main",
        "IRIS STOP    > revenir ici",
    ],
    Mode.READING: [
        "LECTURE",
        "Paume au bord DROIT  > page suivante",
        "Paume au bord GAUCHE > page precedente",
        "  (revenir au centre entre deux pages)",
        "Paume en HAUT / en BAS > defile",
        "",
        "IRIS SOURIS > mode souris",
    ],
    Mode.MOUSE: [
        "SOURIS",
        "Bouger la main = deplacer le curseur",
        "Retirer la main = la reposer ailleurs",
        "",
        "Cliquer a la voix :",
        "  IRIS CLIC   = clic gauche",
        "  IRIS MENU   = clic droit",
        "  IRIS DOUBLE = double clic",
        "  IRIS GLISSE / LACHE = glisser",
        "(main immobile = rien ne se passe)",
        "",
        "Main absente 2 s > LECTURE",
    ],
    Mode.DISABLED: ["DESACTIVE"],
}


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

    # bandes de bord (lecture)
    if core.mode == Mode.READING:
        xl, xr = int(cfg.page_band_left * w), int(cfg.page_band_right * w)
        prog = core.zone_progress
        _blend_rect(cam, 0, xl, (216, 78, 29), 0.25 + (0.5 * prog if core.zone_side == "prev" else 0))
        _blend_rect(cam, xr, w, (216, 78, 29), 0.25 + (0.5 * prog if core.zone_side == "next" else 0))
        _text(cam, "< PAGE", (8, h // 2), 0.6, WHITE, 2)
        _text(cam, "PAGE >", (xr + 8, h // 2), 0.6, WHITE, 2)
        # bandes de défilement (haut / bas, entre les bandes de page)
        yt, yb = int(cfg.scroll_band_top * h), int(cfg.scroll_band_bottom * h)
        sp = core.scroll_progress
        for y0, y1, side, label in ((48, yt, "up", "DEFILE ^"), (yb, h - 28, "down", "DEFILE v")):
            roi = cam[y0:y1, xl:xr]
            a = 0.18 + (0.45 * sp if core.scroll_side == side else 0)
            cv2.addWeighted(np.full_like(roi, (120, 90, 20)), a, roi, 1 - a, 0, roi)
            _text(cam, label, ((xl + xr) // 2 - 40, (y0 + y1) // 2 + 6), 0.55, WHITE, 2)

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
        # bulle « SOURIS ? »
        if core.bubble is not None:
            bx, by = c[0], max(c[1] - 90, 70)
            cv2.rectangle(cam, (bx - 70, by - 26), (bx + 70, by + 10), (12, 65, 194), -1)
            _text(cam, "SOURIS ?", (bx - 58, by), 0.7, WHITE, 2)
            cv2.arrowedLine(cam, (c[0], c[1] - 40), (c[0], by + 14), WHITE, 2, tipLength=0.3)
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

    # bandeau de mode
    cv2.rectangle(cam, (0, 0), (w, 48), MODE_COLORS.get(core.mode, (60, 60, 60)), -1)
    _text(cam, f"MODE : {core.mode}" + ("  (SIMULATION)" if simulation else ""), (12, 33), 0.85, WHITE, 2)
    _text(cam, ("main detectee" if core.palm is not None else "AUCUNE MAIN") + f"   {fps:.0f} img/s"
          "   fermer = STOP", (12, h - 14), 0.5, WHITE if core.palm is not None else (0, 0, 255), 1)

    # confirmation d'action
    if core.last_gesture and now - core.last_gesture[1] < FLASH_S:
        cv2.rectangle(cam, (0, 0), (w - 1, h - 1), GREEN, 8)
        label = core.last_gesture[0]
        scale = 1.3 if len(label) <= 16 else 0.9
        cv2.rectangle(cam, (10, h // 2 + 20), (w - 10, h // 2 + 100 if simulation else h // 2 + 75), (0, 0, 0), -1)
        _text(cam, label, (20, h // 2 + 62), scale, GREEN, 3)
        if simulation:
            _text(cam, "(simulation : rien n'est envoye a Windows)", (20, h // 2 + 90), 0.5, WHITE, 1)

    if cam_status != OK:
        cv2.rectangle(cam, (0, h // 2 - 40), (w, h // 2 + 40), (0, 0, 160), -1)
        _text(cam, f"CAMERA {cam_status.upper()}", (20, h // 2 + 12), 1.1, WHITE, 3)

    # dictée Claude (VS Code) : micro allumé, puis « envoie » / « annule »
    if voice_on and (core.dictating or core.confirming(now)):
        cv2.rectangle(cam, (3, 51), (w - 4, h - 4), (200, 0, 200), 6)
        cv2.rectangle(cam, (0, 52), (w, 92), (120, 0, 120), -1)
        msg = (f"MICRO CLAUDE ({now - core.dictation_t0:.0f} s) - parle, coupe au silence" if core.dictating
               else f"Dis ENVOIE ou ANNULE ({core.confirm_until - now:.0f} s)")
        _text(cam, msg, (10, 79), 0.55, WHITE, 2)
    # écoute vocale
    elif voice_on and core.listening(now):
        cv2.rectangle(cam, (3, 51), (w - 4, h - 4), (255, 220, 0), 4)
        _text(cam, "ECOUTE : dis une commande", (w - 290, 76), 0.55, (255, 220, 0), 2)
    if voice_on and core.last_word and now - core.last_word[1] < 2.0:
        word, _, ok = core.last_word
        _text(cam, f"entendu : {_ascii(word)}" + ("" if ok else " (ecoute fermee)"), (12, h - 40), 0.55,
              (255, 220, 0) if ok else DIM, 1)

    # panneau d'aide
    panel = np.full((h, PANEL_W, 3), 30, np.uint8)
    lines = HELP.get(core.mode, [])
    for i, line in enumerate(lines):
        if i == 0:
            cv2.rectangle(panel, (0, 0), (PANEL_W, 48), MODE_COLORS.get(core.mode, (60, 60, 60)), -1)
            _text(panel, f"GESTES - {line}", (12, 33), 0.7, WHITE, 2)
        else:
            _text(panel, line, (14, 46 + 24 * i), 0.48, WHITE)
    _text(panel, "Les 2 mains marchent : celle qui bouge agit", (12, h - 18), 0.42, DIM)
    if voice_on:
        panel = np.vstack([panel, _voice_panel(core, now, PANEL_W)])
    feed = _feed_box(core, now, w, simulation, max(panel.shape[0] - h, 170))
    cam = np.vstack([cam, feed])
    if panel.shape[0] < cam.shape[0]:
        panel = np.vstack([panel, np.full((cam.shape[0] - panel.shape[0], PANEL_W, 3), 22, np.uint8)])
    return np.hstack([cam, panel])


def _feed_box(core, now, width, simulation, height):
    """Historique des dernières commandes reconnues (gestes et voix), le plus récent en haut."""
    box = np.full((height, width, 3), 20, np.uint8)
    title = "COMMANDES RECONNUES" + ("  (simulation : rien n'est envoye)" if simulation else "")
    _text(box, title, (10, 24), 0.5, WHITE, 1)
    for i, (label, t) in enumerate(reversed(core.feed)):
        age = now - t
        color = GREEN if age < FLASH_S else (WHITE if age < 10 else DIM)
        if "ignore" in label:
            color = (0, 140, 255)
        _text(box, f"{_ascii(label)}", (14, 54 + 24 * i), 0.55, color, 1)
        _text(box, f"il y a {age:.0f} s", (width - 110, 54 + 24 * i), 0.45, DIM, 1)
    if not core.feed:
        _text(box, "(rien pour l'instant)", (14, 54), 0.5, DIM, 1)
    return box


VOICE_HELP = [  # (mot à dire, ce qui se passe) — un mot par ligne
    ("clic", "clic gauche"),
    ("double", "double clic"),
    ("menu", "clic droit"),
    ("defile", "puis monte/descends la main"),
    ("glisse", "tenir le bouton (glisser)"),
    ("lache", "relacher le bouton"),
    ("entree", "touche Entree"),
    ("annule", "touche Echap"),
    ("copie", "Ctrl+C"),
    ("colle", "Ctrl+V"),
    ("claude", "micro Claude (VS Code)"),
    ("", "  coupe au silence, puis"),
    ("", "  ENVOIE ou ANNULE"),
    ("type", "dicter du texte au curseur"),
    ("", "  puis ENVOIE / ANNULE (3 s)"),
    ("pause", "tout desactiver"),
    ("stop", "tout annuler (toujours ecoute)"),
]
CYAN = (255, 220, 0)



def _voice_panel(core, now, width):
    """Bloc d'aide vocale sous le panneau : un mot par ligne, état de l'écoute avec compte à rebours."""
    rows = 2 + len(VOICE_HELP)
    blk = np.full((22 * rows + 24, width, 3), 22, np.uint8)
    if core.listening(now):
        left = max(0.0, core.listen_until - now)
        state = f"ECOUTE OUVERTE ({left:.0f} s)" if left > 0 else "ECOUTE OUVERTE (main immobile)"
        cv2.rectangle(blk, (0, 0), (width, 30), (120, 100, 0), -1)
        _text(blk, state, (10, 21), 0.55, WHITE, 2)
    else:
        _text(blk, "Dis IRIS pour ouvrir l'ecoute", (10, 21), 0.55, CYAN, 1)
    _text(blk, "puis UN mot, seul :", (10, 50), 0.45, DIM)
    for i, (word, what) in enumerate(VOICE_HELP):
        y = 74 + 22 * i
        if word:
            _text(blk, f'"{word}"', (14, y), 0.5, CYAN, 1)
        _text(blk, f"> {what}", (110, y), 0.45, WHITE, 1)
    return blk


def _ascii(s):
    return s.translate(str.maketrans("éèêàâîôûçÉ", "eeeaaioucE"))
