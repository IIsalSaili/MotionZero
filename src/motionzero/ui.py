"""Interface Qt : fenêtre d'aperçu caméra et verre plein écran transparent aux clics.

Le moteur (caméra, MediaPipe, Core) tourne dans un autre fil et envoie ses images par Bridge.
Les signaux Qt émis depuis ce fil arrivent dans le fil de l'interface par la file d'attente Qt.
"""
import ctypes
import os as _os
import time as _time

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QImage, QPainter, QPen,
                           QPixmap)
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

__all__ = ["Bridge", "GlassOverlay", "KeySink", "PreviewWindow", "QApplication", "StopButton"]


class Bridge(QObject):
    frame = Signal(object)   # image BGR (numpy) déjà dessinée par overlay.render
    state = Signal(object)   # état pour le verre : curseur, progression, main perdue
    stop_hover = Signal(float)  # survol du bouton STOP par la main (0..1)
    done = Signal()          # le moteur s'est arrêté


class PreviewWindow(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("motionzero")
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setText("Démarrage de la caméra…")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label)
        self._sized = False

    def set_frame(self, img):
        h, w = img.shape[:2]
        # BGR -> QImage ; .copy() car le tableau numpy peut être réutilisé par le moteur
        qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888).copy()
        self.label.setPixmap(QPixmap.fromImage(qimg))
        if not self._sized:
            self.resize(w, h)
            self._sized = True

    def closeEvent(self, event):
        # la croix n'arrête plus l'appli : seul le bouton STOP le fait. Elle réduit la fenêtre.
        event.ignore()
        self.showMinimized()


# --- Étape 2 : verre plein écran, transparent aux clics -----------------------------------------
_u32 = ctypes.windll.user32
_GWL_EXSTYLE = -20
_WS_EX_LAYERED, _WS_EX_TRANSPARENT = 0x80000, 0x20
_WS_EX_NOACTIVATE, _WS_EX_TOOLWINDOW, _WS_EX_TOPMOST = 0x08000000, 0x80, 0x8
_WDA_EXCLUDEFROMCAPTURE = 0x11
_u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
_u32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]

RING_R = 26        # rayon de l'anneau (px)
RING_W = 5         # épaisseur
HALO_W = 9         # contour noir sous l'anneau blanc : lisible sur fond clair comme sombre


def apply_overlay_style(widget, click_through):
    """Styles Windows posés à la main : Qt seul ne garantit ni « sans focus » ni l'exclusion des captures."""
    hwnd = ctypes.c_void_p(int(widget.winId()))
    ex = _u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    ex |= _WS_EX_LAYERED | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST
    if click_through:
        ex |= _WS_EX_TRANSPARENT
    _u32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex)
    _u32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)  # invisible dans captures et partages


class GlassOverlay(QWidget):
    """Fenêtre plein écran, transparente, au-dessus de tout, que les clics traversent.
    Dessine le curseur de la main et l'anneau de progression en mode souris."""
    closed = Signal()

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)   # options posées une seule fois (les changer recrée la fenêtre)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        scr = QGuiApplication.primaryScreen()
        self.setGeometry(scr.geometry())
        self.dpr = scr.devicePixelRatio()
        self.cursor = None        # position logique (Qt), None = rien à dessiner
        self.progress = 0.0
        self.lost = False
        self.island = _IslandPainter(self.width())   # île Dot Iris (étape 4)

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_style(self, click_through=True)

    def closeEvent(self, event):
        self.closed.emit()     # fermée par Windows (ex. taskkill) : on arrête tout
        super().closeEvent(event)

    def _box(self, pos):
        r = RING_R + HALO_W + 4
        return QRect(int(pos.x() - r), int(pos.y() - r), 2 * r, 2 * r)

    def set_state(self, st):
        """st : dict venu du moteur (pixels physiques de l'écran)."""
        old = self.cursor
        if st.get("show_cursor") and st.get("cursor") is not None:
            x, y = st["cursor"]
            self.cursor = QPointF(x / self.dpr, y / self.dpr)
        else:
            self.cursor = None
        self.progress = st.get("progress", 0.0)
        self.lost = st.get("lost", False)
        if self.island.update(st, _time.perf_counter()):
            self.update(self.island.rect())
        # repeindre seulement autour de l'ancien et du nouveau curseur (Qt recopie la fenêtre à chaque image)
        if old is not None:
            self.update(self._box(old))
        if self.cursor is not None:
            self.update(self._box(self.cursor))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if event.rect().intersects(self.island.rect()):
            self.island.paint(p)
        if self.cursor is None:
            return
        c, r = self.cursor, RING_R
        rect = QRect(int(c.x() - r), int(c.y() - r), 2 * r, 2 * r)
        if self.lost:
            pen = QPen(QColor(150, 150, 150, 200), RING_W, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawEllipse(rect)
            return
        # halo noir + piste blanche translucide
        p.setPen(QPen(QColor(0, 0, 0, 150), HALO_W))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(255, 255, 255, 90), RING_W))
        p.drawEllipse(rect)
        # progression : arc blanc plein, part du haut, sens horaire
        if self.progress > 0:
            p.setPen(QPen(QColor(255, 255, 255), RING_W, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 90 * 16, -int(360 * 16 * min(self.progress, 1.0)))
        # point central blanc cerclé de noir
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(c, 5, 5)


# --- Étape 3 : bouton STOP, petit overlay cliquable en bas à droite -----------------------------
STOP_SIZE = 36      # px logiques : volontairement minuscule (demande de l'utilisateur)
STOP_MARGIN = 6     # écart avec le bord de l'écran et la barre des tâches
STOP_HAND_PAD = 20  # zone élargie pour la main seulement (invisible), sinon trop dur à viser
STOP_RED = QColor(0xD7, 0x19, 0x21)


class StopButton(QWidget):
    """Arrêt d'urgence. Se déclenche au clic de la vraie souris, ou quand le curseur de la main
    reste dessus (le moteur appelle alors directement l'arrêt, sans simuler de clic).
    Ne prend jamais le focus : cliquer dessus ne retire pas le clavier à l'appli en cours."""
    triggered = Signal()
    closed = Signal()

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        scr = QGuiApplication.primaryScreen()
        area = scr.availableGeometry()          # sans la barre des tâches
        self.dpr = scr.devicePixelRatio()
        self.setGeometry(area.right() - STOP_SIZE - STOP_MARGIN, area.bottom() - STOP_SIZE - STOP_MARGIN,
                         STOP_SIZE, STOP_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = 0.0    # progression du survol par la main (0..1)

    def physical_rect(self):
        """Zone du bouton en pixels physiques (ceux du curseur de la main et de SendInput) : x0, y0, x1, y1."""
        g, d, m = self.geometry(), self.dpr, STOP_HAND_PAD
        return (int((g.x() - m) * d), int((g.y() - m) * d),
                int((g.x() + g.width() + m) * d), int((g.y() + g.height() + m) * d))

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_style(self, click_through=False)   # reçoit les clics, mais sans activation

    def set_hover(self, progress):
        if abs(progress - self.hover) > 0.01 or (progress == 0) != (self.hover == 0):
            self.hover = progress
            self.update()

    def mousePressEvent(self, event):
        self.triggered.emit()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 4
        rect = self.rect().adjusted(m, m, -m, -m)
        p.setPen(QPen(QColor(0, 0, 0, 160), 2))       # contour sombre : visible sur fond rouge ou clair
        p.setBrush(STOP_RED)
        p.drawEllipse(rect)
        p.setPen(QColor(255, 255, 255))
        f = p.font()
        f.setFamilies(["Atkinson Hyperlegible", "Segoe UI"])
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "STOP")
        if self.hover > 0:                                # anneau blanc qui se remplit sous la main
            ring = self.rect().adjusted(2, 2, -2, -2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, -int(360 * 16 * min(self.hover, 1.0)))


class KeySink(QWidget):
    """Fenêtre invisible (1 px, hors de l'écran) qui reçoit le raccourci Discord : il ne se tape ainsi
    ni dans la dictée de Claude, ni dans la fenêtre où l'on était (YouTube…)."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(-50, -50, 1, 1)

    def showEvent(self, event):
        super().showEvent(event)
        hwnd = ctypes.c_void_p(int(self.winId()))
        _u32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)


# --- Étape 4 : l'île Dot Iris (en haut au centre, dans le verre) ------------------------------------
_FONT_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                          "assets", "fonts")
ISLAND_TOP = 12          # px depuis le haut de l'écran
ISLAND_H = 46
ISLAND_MAX_W = 960
ISLAND_FADE_S = 3.0      # sans rien de nouveau : l'île s'estompe…
ISLAND_FADED = 0.25      # … à 25 % d'opacité
TOAST_S = 2.5            # durée d'affichage d'une commande comprise / ignorée
MODE_NAMES = {"NEUTRE": "NEUTRE", "LECTURE": "LECTURE", "SOURIS": "SOURIS", "DESACTIVE": "PAUSE"}


def load_fonts():
    """Atkinson Hyperlegible (licence OFL, dans assets/fonts) : conçue pour la lisibilité."""
    for name in ("AtkinsonHyperlegible-Bold.ttf", "AtkinsonHyperlegible-Regular.ttf"):
        QFontDatabase.addApplicationFont(_os.path.join(_FONT_DIR, name))


def island_text(st):
    """(mode affiché, message ou None, actif ?) d'après l'état envoyé par le moteur. Pur : testable."""
    mode = MODE_NAMES.get(st.get("mode"), st.get("mode") or "")
    if st.get("dictating"):
        return mode, "Claude t'écoute", True
    if st.get("confirming"):
        return mode, "Dis ENVOIE ou ANNULE", True
    if st.get("listening"):
        return mode, "Iris écoute…", True
    if st.get("lost") and st.get("mode") == "SOURIS":
        return mode, "Main non détectée", True
    toast, age = st.get("toast"), st.get("toast_age", 1e9)
    if toast and age <= TOAST_S:
        return mode, toast, True
    return mode, None, False


class _IslandPainter:
    """Dessine l'île dans le verre. Ne garde que ce qu'il faut pour l'estomper au repos."""

    def __init__(self, width):
        load_fonts()
        self.font_mode = QFont("Atkinson Hyperlegible", 15, QFont.Weight.Bold)
        self.font_mode.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.font_msg = QFont("Atkinson Hyperlegible", 15)
        self.width = width
        self.content = None
        self.last_change = 0.0
        self.opacity = 1.0

    def rect(self):
        return QRect((self.width - ISLAND_MAX_W) // 2, ISLAND_TOP - 4, ISLAND_MAX_W, ISLAND_H + 8)

    def update(self, st, now):
        mode, msg, active = island_text(st)
        content = (mode, msg)
        if content != self.content:
            self.content, self.last_change = content, now
        idle = now - self.last_change
        target = 1.0 if active or idle < ISLAND_FADE_S else ISLAND_FADED
        changed = abs(target - self.opacity) > 0.01 or idle < 0.1
        self.opacity = target
        return changed

    def paint(self, p):
        if not self.content:
            return
        mode, msg = self.content
        fm_mode, fm_msg = QFontMetrics(self.font_mode), QFontMetrics(self.font_msg)
        pad, dot, gap = 20, 10, 14
        w = pad + dot + 10 + fm_mode.horizontalAdvance(mode) + pad
        if msg:
            msg = fm_msg.elidedText(msg, Qt.TextElideMode.ElideRight, ISLAND_MAX_W - w - gap - pad)
            w += gap + fm_msg.horizontalAdvance(msg)
        x, y = (self.width - w) / 2, ISLAND_TOP
        p.save()
        p.setOpacity(self.opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))                    # noir opaque : lisible sur tout fond
        p.drawRoundedRect(QRectF(x, y, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        cx = x + pad + dot / 2
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, y + ISLAND_H / 2), dot / 2, dot / 2)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        tx = x + pad + dot + 10
        p.drawText(QRectF(tx, y, fm_mode.horizontalAdvance(mode) + 2, ISLAND_H),
                   Qt.AlignmentFlag.AlignVCenter, mode)
        if msg:
            p.setPen(QColor(255, 255, 255, 200))
            p.setFont(self.font_msg)
            mx = tx + fm_mode.horizontalAdvance(mode) + gap
            p.drawText(QRectF(mx, y, w - (mx - x) - pad + 2, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, msg)
        p.restore()
