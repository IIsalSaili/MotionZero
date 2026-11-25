"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52) : constantes et fonctions (2/2, découpé de ui_ile.py, #52)."""
import os as _os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from .ui_ile_base import EYE_AT, EYE_IN_ISLET, EYE_W, ISLET, MODE_NAMES, RING_DEFAULT, TICKER_PAUSE_S, TICKER_SPEED, TOAST_S, _FONT_DIR, _LOGO_DIR


def paint_logo(p, x, y, size, pm, ring=None):
    """Logo d'Iris (île et accueil) : disque clair à fin contour, la main agrandie et centrée sur l'œil,
    découpée par le cercle (le bout des doigts sort du cadre et n'est pas dessiné)."""
    circle = QRectF(x + 1, y + 1, size - 2, size - 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(245, 245, 240))
    p.drawEllipse(circle)
    if pm is not None:
        pw = size * EYE_IN_ISLET / EYE_W                    # largeur affichée de l'image
        ph = pw * pm.height() / pm.width()
        clip = QPainterPath()
        clip.addEllipse(circle)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(QRectF(x + size / 2 - EYE_AT[0] * pw, circle.bottom() - ph, pw, ph), pm, QRectF(pm.rect()))
        p.restore()
    col, width = ring or (RING_DEFAULT, 2.0)
    p.setPen(QPen(col, width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(circle.adjusted(width / 2 - 1, width / 2 - 1, 1 - width / 2, 1 - width / 2))


class HomeLogo(QWidget):
    """Le logo de l'île, en tête de l'accueil (même dessin, même taille)."""

    def __init__(self, size=None):
        super().__init__()
        self.size_px = size or ISLET
        self.setFixedSize(self.size_px, self.size_px)
        pm = QPixmap(_os.path.join(_LOGO_DIR, "neutre.png"))
        self.pm = None if pm.isNull() else pm

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        paint_logo(p, 0, 0, self.size_px, self.pm)
        p.end()


def load_fonts():
    """Atkinson Hyperlegible (licence OFL, dans assets/fonts) : conçue pour la lisibilité."""
    for name in ("AtkinsonHyperlegible-Bold.ttf", "AtkinsonHyperlegible-Regular.ttf"):
        QFontDatabase.addApplicationFont(_os.path.join(_FONT_DIR, name))


CAM_BOX = 56             # caméra barrée (panne), en bas à gauche
CAM_MARGIN = 18
CAM_BLINK_S = 1.2        # période du clignotement (moins de 3 fois par seconde)


def cam_blink(now, motion=True):
    """Opacité de l'icône caméra : pleine puis presque éteinte ; fixe sans animations Windows. Pur."""
    if not motion:
        return 1.0
    return 1.0 if (now % CAM_BLINK_S) < CAM_BLINK_S * 0.6 else 0.25


APP_LABELS = {"chrome.exe": "CHROME", "code.exe": "VS CODE", "discord.exe": "DISCORD", "msedge.exe": "EDGE",
              "firefox.exe": "FIREFOX", "windowsterminal.exe": "TERMINAL", "notepad.exe": "BLOC-NOTES",
              "explorer.exe": "", "winword.exe": "WORD", "excel.exe": "EXCEL", "spotify.exe": "SPOTIFY",
              "whatsapp.exe": "WHATSAPP", "steam.exe": "STEAM"}


def app_label(exe):
    """Nom court de l'appli devant ; vide pour le bureau / l'explorateur ou rien. Pur : testable."""
    if not exe:
        return ""
    exe = exe.lower()
    if exe in APP_LABELS:
        return APP_LABELS[exe]
    name = exe[:-4] if exe.endswith(".exe") else exe
    return name.upper()[:14]


FLAG_ORDER = ("AGRIPPE", "SOURIS", "CANDIDATURE", "FOCUS", "BYPASS")   # le plus important d'abord


def island_text(st):
    """(haut, ligne du bas ou None, actif ?) d'après l'état du moteur. Pur : testable.
    #18 / #27 (demande de l'utilisateur, 24/11) : en haut, un ou deux mots fixes (le mode, plus l'état le plus
    important) ; en bas, une ligne courte qui défile : le dernier retour, sinon les autres états allumés
    (focus, bypass… restent visibles, jamais éteints en silence)."""
    base = MODE_NAMES.get(st.get("mode"), st.get("mode") or "")
    if base == "NEUTRE":                       # 24/11 : l'appli devant (Chrome, VS Code…), sinon rien
        base = app_label(st.get("front"))
    on = {"SOURIS": st.get("mouse"), "FOCUS": st.get("focus"), "BYPASS": st.get("bypass"),
          "CANDIDATURE": st.get("candidature"), "AGRIPPE": st.get("dragging")}
    flags = [f for f in FLAG_ORDER if on[f]]
    shown = flags[:1] if base else flags[:2]
    top = " · ".join(([base] if base else []) + shown)
    rest = " · ".join(f.lower() for f in flags if f not in shown) or None
    head = st.get("pointer") == "tete"
    phase = (st.get("qa") or {}).get("phase")
    pending = (st.get("reminders") or {}).get("pending")
    for cond, text in (
            (phase == "listening", "Ta question"), (phase == "thinking", "Iris réfléchit…"),
            (phase == "searching", "Recherche sur internet…"), (phase == "answer", "Iris répond"),
            (phase == "error", "Question : échec"),
            (st.get("dictating"), "Claude écoute"), (st.get("typing"), "Dictée"),
            (st.get("confirming"), f"{pending} · envoie ?" if pending else "Envoie ou annule"),
            (st.get("listening"), "Écoute"),
            (st.get("lost") and st.get("mouse"), "Visage perdu" if head else "Main perdue"),
            (st.get("arming"), "Tête de face" if head else "Main au centre")):
        if cond:
            return top, text, True
    toast, age = st.get("toast"), st.get("toast_age", 1e9)
    if toast and age <= TOAST_S:
        return top, toast, True
    return top, rest, False


def ticker_offset(text_w, room, elapsed, speed=TICKER_SPEED, pause=TICKER_PAUSE_S):
    """Décalage du texte de la ligne du bas : 0 s'il tient ; sinon il défile, puis repart après une pause. Pur."""
    if text_w <= room:
        return 0.0
    run = (text_w - room) / speed
    k = elapsed % (pause + run + pause)
    if k < pause:
        return 0.0
    return -min((k - pause) * speed, text_w - room)


CLAUDE_ORANGE = "#D97757"
QUOTA_MARGIN = 8          # px entre la pastille du quota et le bord gauche


def paint_claude_logo(p, cx, cy, r):
    """Logo Claude : rond orange, étoile blanche à rayons inégaux (dessinée, pas d'image)."""
    import math
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(CLAUDE_ORANGE))
    p.drawEllipse(QPointF(cx, cy), r, r)
    pen = QPen(QColor(255, 255, 255))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    for i, k in enumerate((0.62, 0.48, 0.58, 0.44, 0.64, 0.5, 0.56, 0.46, 0.62, 0.5, 0.58, 0.45)):
        a = math.radians(i * 30 + 8)
        pen.setWidthF(r * 0.13)
        p.setPen(pen)
        p.drawLine(QPointF(cx, cy), QPointF(cx + math.cos(a) * r * k, cy + math.sin(a) * r * k))
    p.restore()
