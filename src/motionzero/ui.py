"""Interface Qt : fenêtre d'aperçu caméra et verre plein écran transparent aux clics.

Le moteur (caméra, MediaPipe, Core) tourne dans un autre fil et envoie ses images par Bridge.
Les signaux Qt émis depuis ce fil arrivent dans le fil de l'interface par la file d'attente Qt.
"""
import ctypes
import os as _os
import math
import random as _random
import time as _time

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QImage, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

__all__ = ["Bridge", "EyeButton", "GlassOverlay", "KeySink", "PreviewWindow", "QApplication", "StopButton",
           "set_capture_visible"]


class Bridge(QObject):
    frame = Signal(object)   # image BGR (numpy) déjà dessinée par overlay.render
    state = Signal(object)   # état pour le verre : curseur, progression, main perdue
    stop_hover = Signal(float)  # survol du bouton STOP par la main (0..1)
    done = Signal()          # le moteur s'est arrêté
    stats = Signal(object)   # mesures de consommation (panneau de la page d'accueil)
    repair_done = Signal()   # réparation du son finie (fil « reparation » -> bouton, dans le fil Qt)
    pointer = Signal(str)    # souris à la main / à la tête (changé à la voix) -> bouton de l'accueil


class ConsoPanel(QWidget):
    """Panneau « Consommation » de la page d'accueil : motionzero face au PC entier (voir stats.py)."""
    APP, PC, BG, TXT, DIM = QColor(80, 200, 255), QColor(150, 150, 160), QColor(24, 24, 28), QColor(235, 235, 240), \
        QColor(140, 140, 150)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(340)
        self.setMinimumHeight(560)
        self.s = None

    def set_stats(self, s):
        self.s = s
        self.update()

    def _bar(self, p, x, y, w, h, frac, color, base=None):
        p.fillRect(x, y, w, h, QColor(50, 50, 58))
        if base is not None:   # PC entier en gris, motionzero par-dessus en couleur
            p.fillRect(x, y, int(w * min(max(base, 0), 1)), h, self.PC)
        p.fillRect(x, y, int(w * min(max(frac, 0), 1)), h, color)

    def _curve(self, p, x, y, w, h, values, color, top=100.0):
        if len(values) < 2:
            return
        pen = QPen(color, 1.5)
        p.setPen(pen)
        step = w / (60 - 1)
        x0 = x + w - step * (len(values) - 1)
        pts = [QPointF(x0 + i * step, y + h - h * min(v, top) / top) for i, v in enumerate(values)]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self.BG)
        f = QFont("Segoe UI", 10)
        p.setFont(f)
        s, x, w, y = self.s, 14, self.width() - 28, 26

        def text(t, yy, color=None, bold=False, right=None):
            f.setBold(bold)
            p.setFont(f)
            p.setPen(color or self.TXT)
            if right is not None:
                p.drawText(QRect(x, yy - 14, w, 18), Qt.AlignmentFlag.AlignRight, right)
            if t:
                p.drawText(x, yy, t)

        text("CONSOMMATION", y, bold=True)
        f.setBold(False)
        p.setFont(f)
        fm = QFontMetrics(f)
        lx = x + w - fm.horizontalAdvance("motionzero") - fm.horizontalAdvance("PC") - 44
        for label, color in (("motionzero", self.APP), ("PC", self.PC)):
            p.fillRect(lx, y - 9, 8, 8, color)
            p.setPen(self.DIM)
            p.drawText(lx + 12, y, label)
            lx += 12 + fm.horizontalAdvance(label) + 14
        if s is None:
            text("mesure en cours…", y + 30, self.DIM)
            p.end()
            return
        g = lambda k, d=None: s.get(k, d)
        y += 30
        # processeur
        text("Processeur", y, bold=True, right=f"{g('app_cpu', 0):.1f} %  /  PC {g('pc_cpu', 0):.0f} %")
        y += 8
        self._bar(p, x, y, w, 10, g("app_cpu", 0) / 100, self.APP, g("pc_cpu", 0) / 100)
        y += 16
        text(f"motionzero : {g('app_cpu_core', 0):.0f} % d'un cœur  ·  {g('n_threads', 0)} fils", y + 10, self.DIM)
        y += 20
        hist = g("history", {})
        p.fillRect(x, y, w, 44, QColor(32, 32, 38))
        self._curve(p, x, y, w, 44, hist.get("pc_cpu", []), self.PC)
        self._curve(p, x, y, w, 44, hist.get("app_cpu", []), self.APP, top=max(10.0, max(hist.get("app_cpu", [0]) or [0]) * 1.2))
        y += 58
        # cœurs
        cores = g("cores", [])
        text(f"Cœurs ({len(cores)})", y, bold=True)
        y += 8
        if cores:
            cw = (w - (len(cores) - 1) * 4) / len(cores)
            for i, c in enumerate(cores):
                cx = int(x + i * (cw + 4))
                p.fillRect(cx, y, int(cw), 40, QColor(50, 50, 58))
                hh = int(40 * min(c, 100) / 100)
                p.fillRect(cx, y + 40 - hh, int(cw), hh, QColor(255, 120, 80) if c > 85 else self.PC)
        y += 60
        # détail par fil
        text("Par partie de motionzero (% d'un cœur)", y, bold=True)
        y += 6
        for label, pct in (g("threads") or [])[:6]:
            y += 18
            text(label, y, self.DIM, right=f"{pct:.0f} %")
        y += 26
        # mémoire
        text("Mémoire (RAM)", y, bold=True,
             right=f"{g('app_private', 0):.0f} Mo  /  PC {g('pc_ram_used', 0):.1f} sur {g('pc_ram_total', 0):.0f} Go")
        y += 8
        tot = max(g("pc_ram_total", 1), 1e-6) * 1024
        self._bar(p, x, y, w, 10, g("app_private", 0) / tot, self.APP, g("pc_ram_used", 0) * 1024 / tot)
        y += 34
        # carte graphique
        if g("pc_vram_total") is None:
            text("Carte graphique : indisponible", y, bold=True)
            y += 26
        else:
            text("Carte graphique", y, bold=True, right=f"{g('app_gpu', 0):.0f} %  /  PC {g('pc_gpu', 0):.0f} %")
            y += 8
            self._bar(p, x, y, w, 10, g("app_gpu", 0) / 100, self.APP, g("pc_gpu", 0) / 100)
            y += 26
            text("Mémoire vidéo", y, self.DIM,
                 right=f"{g('app_vram', 0) / 1024:.1f} Go  /  PC {g('pc_vram_used', 0) / 1024:.1f} sur "
                       f"{g('pc_vram_total', 0) / 1024:.0f} Go")
            y += 8
            vt = max(g("pc_vram_total", 1), 1e-6)
            self._bar(p, x, y, w, 10, g("app_vram", 0) / vt, self.APP, g("pc_vram_used", 0) / vt)
            y += 34
        # état
        text("État", y, bold=True)
        rows = [("Whisper", "chargé" if g("whisper") else "déchargé (carte graphique libre)"),
                ("Détection de la main", f"{g('detect_hz', 0):.0f} fois / s"),
                ("2e avis vocal", "éveillé" if g("free_awake") else "endormi"),
                ("Priorité", g("priority", "?"))]
        if not g("voice_on", True):
            rows[2] = ("2e avis vocal", "voix coupée")
        for k, v in rows:
            y += 18
            text(k, y, self.DIM, right=v)
        p.end()


def pointer_button_text(pointer):
    """Texte du bouton de l'accueil. Pur : testable."""
    return "Souris : tête  ·  passer à la main" if pointer == "tete" else "Souris : main  ·  passer à la tête"


class PreviewWindow(QWidget):
    closed = Signal()
    pointer_clicked = Signal()                 # « main / tête » : traité par la boucle principale (jamais ici)

    def __init__(self, pointer="main"):
        super().__init__()
        self.setWindowTitle("motionzero")
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setText("Démarrage de la caméra…")
        self.conso = ConsoPanel()
        self.pointer = pointer
        self.pointer_btn = QPushButton(pointer_button_text(pointer))
        self.pointer_btn.setMinimumHeight(56)  # grande cible (clic à la main ou à la tête)
        self.pointer_btn.setStyleSheet("QPushButton { background: #000; color: #fff; border: 1px solid #555;"
                                       " border-radius: 28px; font: bold 13pt 'Atkinson Hyperlegible'; }"
                                       "QPushButton:hover { border-color: #fff; }")
        self.pointer_btn.clicked.connect(self._toggle_pointer)
        side = QVBoxLayout()
        side.setContentsMargins(8, 8, 8, 8)
        side.addWidget(self.conso, 1)
        side.addWidget(self.pointer_btn)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.label, 1)
        lay.addLayout(side)
        self._sized = False
        self.visible_flag = True   # lu par le moteur : réduite, l'aperçu n'est plus dessiné

    def _toggle_pointer(self):
        self.set_pointer("main" if self.pointer == "tete" else "tete")
        self.pointer_clicked.emit()

    def set_pointer(self, pointer):
        """Choix courant (aussi changé à la voix) : le texte du bouton suit."""
        self.pointer = pointer
        self.pointer_btn.setText(pointer_button_text(pointer))

    def changeEvent(self, event):
        super().changeEvent(event)
        self.visible_flag = self.isVisible() and not self.isMinimized()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visible_flag = False

    def showEvent(self, event):
        super().showEvent(event)
        self.visible_flag = not self.isMinimized()

    def set_frame(self, img):
        h, w = img.shape[:2]
        # BGR -> QImage ; .copy() car le tableau numpy peut être réutilisé par le moteur
        qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888).copy()
        self.label.setPixmap(QPixmap.fromImage(qimg))
        if not self._sized:
            self.resize(w + self.conso.width(), max(h, self.conso.minimumHeight()))
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

LOUPE_D = 200      # diamètre de la loupe (px), toujours affichée en mode souris
LOUPE_ZOOM = 2.5
LOUPE_GAP = 40     # écart entre le curseur et le bord de la loupe (elle ne cache pas la cible)
RING_R = 26        # rayon de l'anneau (px)
RING_W = 5         # épaisseur
HALO_W = 9         # contour noir sous l'anneau blanc : lisible sur fond clair comme sombre


def set_capture_visible(widget, visible):
    """Visible ou non dans les captures et partages d'écran (Discord, OBS…)."""
    _u32.SetWindowDisplayAffinity(ctypes.c_void_p(int(widget.winId())), 0 if visible else _WDA_EXCLUDEFROMCAPTURE)


def apply_overlay_style(widget, click_through, in_captures=True):
    """Styles Windows posés à la main : Qt seul ne garantit pas « sans focus ». in_captures : visible ou non
    dans les captures et partages (par défaut visible, demande de l'utilisateur)."""
    hwnd = ctypes.c_void_p(int(widget.winId()))
    ex = _u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    ex |= _WS_EX_LAYERED | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST
    if click_through:
        ex |= _WS_EX_TRANSPARENT
    _u32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex)
    set_capture_visible(widget, in_captures)


class GlassOverlay(QWidget):
    """Fenêtre plein écran, transparente, au-dessus de tout, que les clics traversent. Deux rôles :
    - « ui » : l'île, le logo, la pastille Discord. Visible dans les partages (bouton œil pour masquer) ;
    - « cursor » : le curseur de la main et la loupe. TOUJOURS exclue des captures : la loupe capture
      l'écran autour du curseur, elle se filmerait elle-même sinon."""
    closed = Signal()

    def __init__(self, role="ui"):
        self.role = role
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
        self.loupe = None         # (centre de la loupe, image agrandie) ou None
        self.progress = 0.0
        self.lost = False
        self.ghost = None         # (main, centre, rayon) en coordonnées Qt, ou None
        self.gauge = None         # jauge du défilement vocal (voir gauge_geometry), ou None
        self.hand_icon = None
        if role != "ui":
            from PySide6.QtCore import QByteArray
            from PySide6.QtSvg import QSvgRenderer
            try:
                with open(_os.path.join(_ICON_DIR, "hand.svg"), encoding="utf-8") as f:
                    self.hand_icon = QSvgRenderer(QByteArray(f.read().replace("currentColor", "#d0d0d0").encode()))
            except OSError:
                self.hand_icon = None     # sans l'icône : un simple disque gris
        self.island = _IslandPainter(self.width()) if role == "ui" else None   # île Dot Iris
        self.vol = None           # barre de volume (« iris volume ») : {"level", "muted"} ou None
        self._last_st = {}
        self._anim = QTimer(self)                 # tourne seulement pendant une animation (logo, alarme)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._anim_tick)

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_style(self, click_through=True, in_captures=self.role == "ui")

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
        old_ghost = self.ghost
        self.ghost = ghost_geometry(st, self.dpr) if self.island is None else None
        old_gauge = self.gauge
        self.gauge = gauge_geometry(st, self.width(), self.height()) if self.island is None else None
        if old_gauge != self.gauge:
            for g in (old_gauge, self.gauge):
                if g is not None:
                    self.update(g["box"])
        if self.island is not None:
            vol = st.get("volume")
            if vol != self.vol:
                self.vol = vol
                self.update(volume_rect(self.width(), self.height()).toAlignedRect().adjusted(-4, -4, 4, 4))
            self._last_st = st
            now = _time.perf_counter()
            if self.island.update(st, now):
                self.update(self.island.rect())
            if self.island.animating(now) and not self._anim.isActive():
                self._anim.start()
            self.cursor = None                # le curseur et la loupe sont dans la fenêtre « cursor »
            return
        old_loupe = self._loupe_box()
        self._grab_loupe(st)
        for box in (old_loupe, self._loupe_box()):
            if box is not None:
                self.update(box)
        # repeindre seulement autour de l'ancien et du nouveau curseur (Qt recopie la fenêtre à chaque image)
        for g in (old_ghost, self.ghost):
            if g is not None:
                self.update(_ghost_box(g))
        if old is not None:
            self.update(self._box(old))
        if self.cursor is not None:
            self.update(self._box(self.cursor))

    def _paint_gauge(self, p):
        g = self.gauge
        track = g["track"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(track, track.width() / 2, track.width() / 2)
        band = g["band"]
        if g["armed"]:                                        # zone neutre : la page ne bouge pas
            p.setBrush(QColor(52, 199, 89, 150))
            p.drawRoundedRect(band, 6, 6)
        else:                                                 # centre à atteindre, comme la souris
            p.setBrush(Qt.BrushStyle.NoBrush)
            for col, w in ((QColor(0, 0, 0, 110), 4), (QColor(220, 220, 220, 170), 2)):
                p.setPen(QPen(col, w, Qt.PenStyle.DashLine))
                p.drawRoundedRect(band, 6, 6)
        if g["hand"] is None:
            return
        box = g["hand"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(box.adjusted(-8, -8, 8, 8))
        p.setOpacity(0.85)
        if self.hand_icon is not None:
            self.hand_icon.render(p, box)
        else:
            p.setBrush(QColor(200, 200, 200))
            p.drawEllipse(box)
        p.setOpacity(1.0)

    def _paint_ghost(self, p):
        hand, ctr, r = self.ghost
        p.setBrush(Qt.BrushStyle.NoBrush)
        for col, w in ((QColor(0, 0, 0, 110), 4), (QColor(220, 220, 220, 170), 2)):   # zone du centre
            p.setPen(QPen(col, w, Qt.PenStyle.DashLine))
            p.drawEllipse(ctr, r, r)
        box = QRectF(hand.x() - GHOST_S / 2, hand.y() - GHOST_S / 2, GHOST_S, GHOST_S)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))                       # pastille sombre : lisible sur fond clair
        p.drawEllipse(box.adjusted(-8, -8, 8, 8))
        p.setOpacity(0.85)
        if self.hand_icon is not None:
            self.hand_icon.render(p, box)
        else:
            p.setBrush(QColor(200, 200, 200))
            p.drawEllipse(box)
        p.setOpacity(1.0)

    def _anim_tick(self):
        now = _time.perf_counter()
        self.island.update(self._last_st, now)
        self.update(self.island.rect())
        if not self.island.animating(now):
            self._anim.stop()

    def _loupe_center(self):
        """En haut à droite du curseur ; de l'autre côté près des bords de l'écran."""
        c = self.cursor
        off = LOUPE_GAP + LOUPE_D / 2
        dx = off if c.x() + off + LOUPE_D / 2 < self.width() else -off
        dy = -off if c.y() - off - LOUPE_D / 2 > 0 else off
        return QPointF(c.x() + dx, c.y() + dy)

    def _loupe_box(self):
        if self.loupe is None:
            return None
        ctr = self.loupe[0]
        r = LOUPE_D // 2 + 4
        return QRect(int(ctr.x() - r), int(ctr.y() - r), 2 * r, 2 * r)

    def _grab_loupe(self, st):
        """Capture la petite zone sous le curseur (l'overlay de motionzero en est exclu)."""
        if self.cursor is None or not st.get("show_cursor") or st.get("lost"):
            self.loupe = None
            return
        src = LOUPE_D / LOUPE_ZOOM
        scr = QGuiApplication.primaryScreen()
        pm = scr.grabWindow(0, int(self.cursor.x() - src / 2), int(self.cursor.y() - src / 2), int(src), int(src))
        self.loupe = (self._loupe_center(), pm)

    def _paint_loupe(self, p):
        ctr, pm = self.loupe
        r = LOUPE_D / 2
        circle = QRectF(ctr.x() - r, ctr.y() - r, LOUPE_D, LOUPE_D)
        clip = QPainterPath()
        clip.addEllipse(circle)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(circle, pm, QRectF(pm.rect()))
        p.restore()
        p.setPen(QPen(QColor(0, 0, 0, 200), 4))                 # bord : noir + blanc, lisible partout
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(circle)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(circle)
        for col, w in ((QColor(0, 0, 0, 200), 4), (QColor(255, 255, 255), 2)):   # croix au centre
            p.setPen(QPen(col, w))
            p.drawLine(QPointF(ctr.x() - 9, ctr.y()), QPointF(ctr.x() + 9, ctr.y()))
            p.drawLine(QPointF(ctr.x(), ctr.y() - 9), QPointF(ctr.x(), ctr.y() + 9))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.loupe is not None and event.rect().intersects(self._loupe_box()):
            self._paint_loupe(p)
        if self.island is not None and event.rect().intersects(self.island.rect()):
            self.island.paint(p)
        if self.vol is not None:
            paint_volume(p, volume_rect(self.width(), self.height()), self.vol["level"], self.vol["muted"])
        if self.ghost is not None:
            self._paint_ghost(p)
        if self.gauge is not None:
            self._paint_gauge(p)
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
STOP_MARGIN = 2     # collés au bas de l'écran (demande de l'utilisateur, 12/11 : plus de marge au-dessus)
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
        area = scr.geometry()                   # tout en bas de l'écran, sur la barre des tâches
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


class EyeButton(QWidget):
    """Petit bouton à gauche du STOP : un clic masque / démasque l'overlay dans les captures et partages.
    Par défaut l'overlay est visible (œil ouvert). Le curseur et la loupe restent toujours masqués."""
    toggled = Signal(bool)

    def __init__(self, stop_btn):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        g = stop_btn.geometry()
        self.setGeometry(g.x() - STOP_SIZE - STOP_MARGIN, g.y(), STOP_SIZE, STOP_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Montrer / masquer motionzero dans les partages d'écran")
        self.visible_in_captures = True
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        self.icons = {}
        for name in ("eye", "eye-off"):
            try:
                svg = open(_os.path.join(_ICON_DIR, f"{name}.svg"), encoding="utf-8").read()
                self.icons[name] = QSvgRenderer(QByteArray(svg.replace("currentColor", "#ffffff").encode()))
            except OSError:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_style(self, click_through=False, in_captures=self.visible_in_captures)

    def mousePressEvent(self, event):
        self.visible_in_captures = not self.visible_in_captures
        set_capture_visible(self, self.visible_in_captures)
        self.update()
        self.toggled.emit(self.visible_in_captures)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        p.setPen(QPen(QColor(255, 255, 255, 160), 2))
        p.setBrush(QColor(0, 0, 0, 220))
        p.drawEllipse(rect)
        r = self.icons.get("eye" if self.visible_in_captures else "eye-off")
        if r is not None:
            m = 9
            r.render(p, QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m))


class RepairButton(QWidget):
    """« Réparer le son », tout en bas à gauche. Seulement à la demande (clic ou geste) : jamais automatique,
    le bouton mute du casque ou un long silence ne doivent rien déclencher."""
    triggered = Signal()

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        area = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(area.left() + STOP_MARGIN, area.bottom() - STOP_SIZE - STOP_MARGIN, STOP_SIZE, STOP_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Réparer le son (micro figé) sans redémarrer le PC")
        self.busy = False
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        try:
            svg = open(_os.path.join(_ICON_DIR, "mic.svg"), encoding="utf-8").read()
            self.icon = QSvgRenderer(QByteArray(svg.replace("currentColor", "#ffffff").encode()))
        except OSError:
            self.icon = None

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_style(self, click_through=False)

    def set_busy(self, busy):
        self.busy = busy
        self.update()

    def mousePressEvent(self, event):
        if not self.busy:
            self.triggered.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        p.setPen(QPen(QColor(255, 255, 255, 160), 2))
        p.setBrush(QColor(28, 38, 70, 230) if self.busy else QColor(0, 0, 0, 220))
        p.drawEllipse(rect)
        if self.icon is not None:
            m = 10
            self.icon.render(p, QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m))


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
ANSWER_W = 560           # largeur de l'île agrandie pour une réponse de Claude
ANSWER_MAX_H = 440      # 3 phrases longues tiennent ; au-delà, le texte est coupé proprement
ISLAND_H = 46
ISLAND_MAX_W = 960
ISLAND_FADE_S = 3.0      # sans rien de nouveau : l'île s'estompe…
ISLAND_FADED = 0.25      # … à 25 % d'opacité
TOAST_S = 2.5            # durée d'affichage d'une commande comprise / ignorée
MODE_NAMES = {"NEUTRE": "NEUTRE", "LECTURE": "LECTURE", "SOURIS": "SOURIS", "CHROME": "CHROME", "DESACTIVE": "PAUSE"}

# pastille Discord, à gauche de l'îlot : micro barré (micro coupé), casque barré + micro barré (sourdine)
_ICON_DIR = _os.path.join(_os.path.dirname(_FONT_DIR), "icons")
DISCORD_RED = "#ED4245"
ICON = 24


def discord_icons(state):
    """Icônes à afficher d'après (micro coupé, sourdine). Pur : testable."""
    if not state:
        return []
    mute, deaf = state
    if deaf:
        return ["headphone-off", "mic-off"]
    return ["mic-off"] if mute else []


# îlot du logo d'Iris, à gauche de l'île (un disque clair : la main noire du neutre reste lisible)
_LOGO_DIR = _os.path.join(_os.path.dirname(_FONT_DIR), "iris")
ISLET = 64               # diamètre de l'îlot (l'île du texte garde sa hauteur)
ISLET_GAP = 8
OK_FLASH_S = 0.5         # main verte : commande vocale comprise
BLINK_S = 0.25           # œil fermé (un clignement humain dure environ 0,1 à 0,4 s)
BLINK_EVERY = (1.2, 1.8) # environ toutes les 1,5 s, un peu irrégulier pour ne pas faire métronome
EYE_AT = (0.560, 0.690)  # centre de l'œil dans l'image du logo (mesuré sur assets/iris/neutre.png)
EYE_W = 0.31             # largeur de l'œil / largeur de l'image
EYE_IN_ISLET = 0.32      # zoom choisi (« B ») : la paume remplit le cercle, le haut des doigts sort du cadre


REMINDER_W = 560
CAL_W = 1060             # calendrier : 7 cartes
CAL_H = 470
BLUE = QColor(111, 155, 245)
ORANGE = QColor(245, 165, 36)
ALARM_RED = (190, 30, 40)


CLOCK_GAP = 8            # écart entre l'île et la fiche de l'heure, en dessous
CLOCK_BIG = 2 * ISLAND_H + CLOCK_GAP   # logo agrandi : la hauteur des deux bandeaux empilés
CLOCK_ANIM_S = 0.6       # durée de l'agrandissement (et du retour)


def _ease(u):
    """Accélère puis ralentit (0 -> 1)."""
    u = min(max(u, 0.0), 1.0)
    return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def clock_anim(now, start, end):
    """(agrandissement 0..1, angle en degrés) du logo pendant « iris heure ». Pur : testable.
    Aller : rotation vers la gauche en grossissant ; retour : vers la droite en rapetissant."""
    if start is None:
        return 0.0, 0.0
    if end is None:
        e = _ease((now - start) / CLOCK_ANIM_S)
        return e, -360.0 * e
    e = _ease((now - end) / CLOCK_ANIM_S)
    return 1.0 - e, 360.0 * e


DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def clock_text(now):
    """« jeudi 12/11/2026 · 14:05 ». Pur : testable."""
    return f"{DAYS[now.weekday()]} {now:%d/%m/%Y · %H:%M}"


def reminder_view(st):
    """Ce que l'île montre pour les rappels : ("current", dict) | ("list", lignes) | None. Pur : testable.
    Le rappel déclenché passe avant tout (il reste jusqu'à « iris merci »), puis la liste demandée."""
    rem = st.get("reminders") or {}
    if rem.get("current"):
        return "current", rem["current"]
    if rem.get("calendar"):
        return "calendar", rem["calendar"]
    if rem.get("list"):
        return "list", rem["list"]
    return None


def reminder_texts(kind, data):
    """(titre, texte, ligne du bas) de la carte des rappels. Pur : testable."""
    if kind == "list":
        return ("RAPPELS À VENIR", "\n".join(data), "« Iris rappel » pour en ajouter ou en supprimer")
    title = ("ALARME" if data.get("alarm") else "RAPPEL") + (" MANQUÉ" if data.get("missed") else "")
    title += f" · {data.get('when', '')}"
    meta = "« Iris merci » : noté · « Iris plus tard » : +10 min"
    if data.get("ringing"):
        meta = "« stop » : silence · " + meta
    if data.get("more"):
        title += f" · +{data['more']} en attente"
    return title, data.get("text", ""), meta


GHOST_S = 56     # taille de la main fantôme (px logiques)
VOL_W, VOL_H, VOL_MARGIN = 64, 300, 24      # barre de volume, à droite, centrée en hauteur


def volume_rect(w, h):
    return QRectF(w - VOL_MARGIN - VOL_W, (h - VOL_H) / 2, VOL_W, VOL_H)


def volume_fill(level, track_h):
    """Hauteur remplie de la jauge pour un volume 0..100. Pur : testable."""
    return track_h * max(0, min(100, level)) / 100


def paint_volume(p, box, level, muted):
    """Même style que l'île : noir opaque, blanc, police Atkinson. Gris seulement pour le vide et l'état muet."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0))
    p.drawRoundedRect(box, box.width() / 2, box.width() / 2)
    track = QRectF(box.center().x() - 5, box.top() + 30, 10, box.height() - 100)
    p.setBrush(QColor(255, 255, 255, 45))
    p.drawRoundedRect(track, 5, 5)
    fill = volume_fill(level, track.height())
    if fill > 0:
        p.setBrush(QColor(255, 255, 255, 110) if muted else QColor(255, 255, 255))
        p.drawRoundedRect(QRectF(track.left(), track.bottom() - fill, track.width(), fill), 5, 5)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Atkinson Hyperlegible", 20, QFont.Weight.Bold))
    num = QRectF(box.left(), track.bottom() + 10, box.width(), 32)
    p.drawText(num, Qt.AlignmentFlag.AlignCenter, f"{level}")
    p.setPen(QColor(255, 255, 255, 150))
    p.setFont(QFont("Atkinson Hyperlegible", 10))
    p.drawText(QRectF(box.left(), num.bottom() - 2, box.width(), 20), Qt.AlignmentFlag.AlignCenter,
               "muet" if muted else "%")
    p.restore()


def ghost_geometry(st, dpr):
    """Main fantôme : (position de la main, centre visé, rayon) en coordonnées Qt, ou None. Pur : testable."""
    g = st.get("ghost")
    if not g or not st.get("arming"):
        return None
    cur = st.get("cursor")
    x, y, r = g
    ctr = QPointF(cur[0] / dpr, cur[1] / dpr) if cur is not None else QPointF(x / dpr, y / dpr)
    return (QPointF(x / dpr, y / dpr), ctr, r / dpr)


GAUGE_W = 14            # largeur de la jauge de défilement (px Qt)
GAUGE_MARGIN = 40       # distance au bord droit de l'écran


def gauge_geometry(st, w, h):
    """Jauge du défilement vocal au bord droit : piste verticale (60 % de la hauteur d'écran), bande du centre,
    icône de main à la hauteur de la main. Pur : testable. None hors défilement."""
    g = st.get("scroll_gauge")
    if not g:
        return None
    y, armed, arm, dead = g
    top, height = h * 0.2, h * 0.6
    x = w - GAUGE_MARGIN - GAUGE_W
    track = QRectF(x, top, GAUGE_W, height)
    half = (dead if armed else arm) * height
    band = QRectF(x - 10, top + height / 2 - half, GAUGE_W + 20, 2 * half)
    hand = None
    if y is not None:
        hy = top + min(max(y, 0.0), 1.0) * height
        hand = QRectF(x + GAUGE_W / 2 - GHOST_S / 2, hy - GHOST_S / 2, GHOST_S, GHOST_S)
    m = GHOST_S / 2 + 12
    box = QRectF(x + GAUGE_W / 2 - m, top - m, 2 * m, height + 2 * m).toAlignedRect()
    return {"track": track, "band": band, "hand": hand, "armed": armed, "box": box}


def _ghost_box(g):
    hand, ctr, r = g
    m = GHOST_S / 2 + 12
    a = QRect(int(hand.x() - m), int(hand.y() - m), int(2 * m), int(2 * m))
    b = QRect(int(ctr.x() - r - 6), int(ctr.y() - r - 6), int(2 * r + 12), int(2 * r + 12))
    return a.united(b)


def islet_logo(st, blinking):
    """Nom du logo à afficher. Pur : testable. Toujours le logo noir classique ; le mode se lit au cercle."""
    return "neutre_ferme" if blinking else "neutre"


RING_DEFAULT = QColor(0, 0, 0, 200)
RING_BY_MODE = {"SOURIS": ORANGE, "CHROME": BLUE}
GREEN = QColor(52, 199, 89)
RING_BLINK_S = 0.125     # commande comprise : 2 éclats verts pendant les 0,5 s de « ok_flash »


def islet_ring(st, age):
    """Couleur et épaisseur du cercle autour de la main. Pur : testable.
    Orange quand la souris est allumée (quel que soit le mode), bleu en Chrome ; une commande comprise le fait
    clignoter en vert."""
    if st.get("ok_flash") and int(age / RING_BLINK_S) % 2 == 0:
        return GREEN, 3.5
    col = ORANGE if st.get("mouse") else RING_BY_MODE.get(st.get("mode"))
    return (col, 3.5) if col is not None else (RING_DEFAULT, 2.0)


def load_fonts():
    """Atkinson Hyperlegible (licence OFL, dans assets/fonts) : conçue pour la lisibilité."""
    for name in ("AtkinsonHyperlegible-Bold.ttf", "AtkinsonHyperlegible-Regular.ttf"):
        QFontDatabase.addApplicationFont(_os.path.join(_FONT_DIR, name))


def island_text(st):
    """(mode affiché, message ou None, actif ?) d'après l'état envoyé par le moteur. Pur : testable."""
    mode = MODE_NAMES.get(st.get("mode"), st.get("mode") or "")
    if st.get("mouse"):
        mode = "SOURIS" if mode in ("NEUTRE", "") else f"{mode} · SOURIS"   # la souris s'ajoute au mode
    qa = st.get("qa") or {}
    if qa.get("phase") == "listening":
        return mode, "Pose ta question…", True
    if qa.get("phase") == "thinking":
        return mode, "Claude réfléchit…", True
    if qa.get("phase") == "answer":
        return mode, "Claude répond", True
    if qa.get("phase") == "error":
        return mode, "Question : échec", True
    if st.get("dictating"):
        return mode, "Claude t'écoute", True
    if st.get("typing"):
        return mode, "Dicte ton texte…", True
    if st.get("confirming"):
        return mode, "Dis ENVOIE ou ANNULE", True
    if st.get("listening"):
        return mode, "Iris écoute…", True
    if st.get("lost") and st.get("mouse"):
        return mode, "Main non détectée", True
    if st.get("arming"):
        return mode, "Main au centre pour démarrer", True
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
        self.font_answer = QFont("Atkinson Hyperlegible", 17)
        self.font_small = QFont("Atkinson Hyperlegible", 12)
        self.qa = None
        self.width = width
        self.content = None
        self.last_change = 0.0
        self.opacity = 1.0
        self.logos = {}
        for name in ("neutre", "neutre_ferme", "lecture", "lecture_ferme", "souris", "souris_ferme", "ok"):
            pm = QPixmap(_os.path.join(_LOGO_DIR, f"{name}.png"))
            if not pm.isNull():
                self.logos[name] = pm
        self.logo = None
        self.ring = (RING_DEFAULT, 2.0)
        self.flash_t0 = None
        self.icons = {}
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        for name, color in (("mic-off", DISCORD_RED), ("headphone-off", DISCORD_RED), ("bell", "#FFFFFF"), ("clock", "#FFFFFF"), ("timer", "#FFFFFF")):
            try:
                svg = open(_os.path.join(_ICON_DIR, f"{name}.svg"), encoding="utf-8").read()
                self.icons[name] = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode()))
            except OSError:
                pass
        self.rem = None          # ("current", dict) | ("list", lignes) | None
        self.next_rem = None     # texte de l'heure (« iris heure »), gardé pendant l'animation de retour
        self.clk_start = None    # début de l'agrandissement du logo
        self.clk_end = None      # début du retour
        self.font_rem = QFont("Atkinson Hyperlegible", 22, QFont.Weight.Bold)
        self.discord = []
        self.blink_until = 0.0
        self.next_blink = 0.0

    def rect(self):
        w = max(ISLAND_MAX_W + 2 * (ISLET + ISLET_GAP) + 2 * 120, CAL_W + 40)   # + pastille Discord / calendrier
        h = max(ISLET + ANSWER_MAX_H + 8, ISLET + 14 + 56 + CAL_H + 10)
        return QRect(int((self.width - w) // 2), ISLAND_TOP - 4, int(w), h)

    def update(self, st, now):
        mode, msg, active = island_text(st)
        qa = st.get("qa") or {}
        self.qa = qa if qa.get("phase") in ("answer", "error") else None
        self.rem = reminder_view(st)
        tm = (st.get("reminders") or {}).get("timers") or {}
        self.timer_pills = [("Chrono " + tm["chrono"]["text"] + (" · arrêté" if tm["chrono"]["done"] else ""), False)] \
            if tm.get("chrono") else []
        if tm.get("timer"):
            self.timer_pills.append(("Timer " + tm["timer"]["text"], True))
        if self.timer_pills:
            active = True
        clock = st.get("clock")                # « jeudi 12/11/2026 · 14:05 », seulement après « iris heure »
        if clock and (self.clk_start is None or self.clk_end is not None):
            self.clk_start, self.clk_end = now, None          # (re)commence l'aller
        elif not clock and self.clk_start is not None and self.clk_end is None:
            self.clk_end = now                                 # le retour commence
        if self.clk_end is not None and now - self.clk_end >= CLOCK_ANIM_S:
            self.clk_start = self.clk_end = None               # le logo a repris sa place
        if clock:
            self.next_rem = clock
        elif self.clk_start is None:
            self.next_rem = None
        self.anim_now = now
        if self.next_rem:
            active = True
        if self.rem:
            active = True
        rem_key = (self.rem[0], str(self.rem[1])) if self.rem else None
        content = (mode, msg, (qa.get("phase"), qa.get("answer"), int(qa.get("left", 0))) if self.qa else None,
                   rem_key, self.next_rem, tuple(self.timer_pills))
        if content != self.content:
            self.content, self.last_change = content, now
        if st.get("ok_flash"):
            self.last_change = now
        # clignement : 0,5 s, à intervalle irrégulier
        if now >= self.next_blink:
            self.blink_until = now + BLINK_S
            self.next_blink = now + _random.uniform(*BLINK_EVERY)
        logo = islet_logo(st, now < self.blink_until)
        if st.get("ok_flash"):
            self.flash_t0 = now if self.flash_t0 is None else self.flash_t0
        else:
            self.flash_t0 = None
        ring = islet_ring(st, now - self.flash_t0 if self.flash_t0 is not None else 0.0)
        discord = discord_icons(st.get("discord"))
        if discord != self.discord:
            self.discord, self.last_change = discord, now
        idle = now - self.last_change
        target = 1.0 if active or idle < ISLAND_FADE_S else ISLAND_FADED
        ringing = bool(self.rem and self.rem[0] == "current" and self.rem[1].get("ringing"))
        changed = (abs(target - self.opacity) > 0.01 or idle < 0.1 or logo != self.logo or ring != self.ring or ringing
                   or self.animating(now))
        self.opacity, self.logo, self.ring = target, logo, ring
        return changed

    def animating(self, now):
        """Vrai pendant l'animation du logo ou une alarme qui pulse : redessiner à 60 images/s."""
        moving = self.clk_start is not None and (self.clk_end is not None or now - self.clk_start < CLOCK_ANIM_S)
        ringing = bool(self.rem and self.rem[0] == "current" and self.rem[1].get("ringing"))
        return moving or ringing

    def paint(self, p):
        if not self.content:
            return
        mode, msg = self.content[0], self.content[1]
        if self.rem and self.rem[0] == "calendar":
            self._paint_calendar(p, self.rem[1])
            return
        if self.rem:
            self._paint_reminder(p, *self.rem)
            return
        if getattr(self, "qa", None):
            self._paint_answer(p, mode, msg)
            return
        fm_mode, fm_msg = QFontMetrics(self.font_mode), QFontMetrics(self.font_msg)
        pad, dot, gap = 20, 10, 14
        w = pad + dot + 10 + fm_mode.horizontalAdvance(mode) + pad
        if msg:
            msg = fm_msg.elidedText(msg, Qt.TextElideMode.ElideRight, ISLAND_MAX_W - w - gap - pad)
            w += gap + fm_msg.horizontalAdvance(msg)
        gx = (self.width - (ISLET + ISLET_GAP + w)) / 2       # îlot + île, centrés ensemble
        x, y = gx + ISLET + ISLET_GAP, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)       # le logo ne s'estompe jamais
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
        self._paint_clock(p, x, y + ISLAND_H + CLOCK_GAP)
        ty = y + ISLAND_H + CLOCK_GAP
        if self.next_rem:
            ty += ISLAND_H + CLOCK_GAP
        tx = x
        for text, countdown in getattr(self, "timer_pills", []):
            tx += self._paint_timer_pill(p, tx, ty, text, countdown) + CLOCK_GAP

    def _paint_timer_pill(self, p, x, y, text, countdown):
        """Fiche « sablier + temps » ; renvoie sa largeur."""
        fm = QFontMetrics(self.font_msg)
        pad, gap = 18, 10
        w = 2 * pad + ICON + gap + fm.horizontalAdvance(text)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(28, 38, 70, 245) if countdown else QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        icon = self.icons.get("timer")
        if icon is not None:
            icon.render(p, QRectF(x + pad, y + (ISLAND_H - ICON) / 2, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + ICON + gap, y, w, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, text)
        p.restore()
        return w

    def _paint_clock(self, p, x, y):
        """Fiche « horloge + jour, date, heure », sous l'île ; apparaît avec l'agrandissement du logo."""
        if not self.next_rem:
            return
        k, _ = clock_anim(getattr(self, "anim_now", 0.0), self.clk_start, self.clk_end)
        if k <= 0.01:
            return
        fm = QFontMetrics(self.font_msg)
        pad, gap = 18, 10
        w = 2 * pad + ICON + gap + fm.horizontalAdvance(self.next_rem)
        p.save()
        p.setOpacity(k)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        clock = self.icons.get("clock")
        if clock is not None:
            clock.render(p, QRectF(x + pad, y + (ISLAND_H - ICON) / 2, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + ICON + gap, y, w, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, self.next_rem)
        p.restore()

    def _paint_answer(self, p, mode, header):
        """L'île agrandie vers le bas : en-tête, la question en petit, la réponse, le temps restant."""
        qa = self.qa
        pad, top = 20, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        gx = (self.width - (ISLET + ISLET_GAP + ANSWER_W)) / 2
        x = gx + ISLET + ISLET_GAP
        inner = ANSWER_W - 2 * pad
        fm_q = QFontMetrics(self.font_small)
        fm_a = QFontMetrics(self.font_answer)
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        q_text = f"« {qa.get('question')} »" if qa.get("question") else ""
        q_rect = fm_q.boundingRect(QRect(0, 0, inner, 1000), flags, q_text) if q_text else QRect()
        a_rect = fm_a.boundingRect(QRect(0, 0, inner, 1000), flags, qa.get("answer") or "")
        meta = f"Haiku · disparaît dans {int(qa.get('left', 0))} s · « Iris, ferme » pour la retirer"
        h = min(ANSWER_MAX_H, 44 + (q_rect.height() + 8 if q_text else 0) + a_rect.height() + 40)
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 240))
        p.drawRoundedRect(QRectF(x, top, ANSWER_W, h), 22, 22)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(x + pad + 5, top + 23), 5, 5)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(x + pad + 20, top, inner, 46), Qt.AlignmentFlag.AlignVCenter, mode)
        fm_mode = QFontMetrics(self.font_mode)
        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + 34 + fm_mode.horizontalAdvance(mode), top, inner, 46),
                   Qt.AlignmentFlag.AlignVCenter, header)
        y = top + 44
        if q_text:
            p.setPen(QColor(255, 255, 255, 150))
            p.setFont(self.font_small)
            p.drawText(QRectF(x + pad, y, inner, q_rect.height()), flags, q_text)
            y += q_rect.height() + 8
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_answer)
        p.save()
        p.setClipRect(QRectF(x + pad, y, inner, max(0, top + h - 36 - y)))   # jamais sur la ligne du bas
        p.drawText(QRectF(x + pad, y, inner, a_rect.height()), flags, qa.get("answer") or "")
        p.restore()
        p.setPen(QColor(255, 255, 255, 110))
        p.setFont(self.font_small)
        p.drawText(QRectF(x + pad, top + h - 28, inner, 22), Qt.AlignmentFlag.AlignVCenter, meta)
        p.restore()

    def _paint_calendar(self, p, cal):
        """« iris calendrier » : ruban du mois, 7 cartes de la semaine (ou un jour en grand), consignes."""
        gx = (self.width - (ISLET + ISLET_GAP + 300)) / 2
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)
        # en-tête dans l'île
        x0 = gx + ISLET + ISLET_GAP
        y0 = ISLAND_TOP + (ISLET - ISLAND_H) / 2
        fm_mode = QFontMetrics(self.font_mode)
        head = f"{cal['title']}"
        w = 20 + 10 + 10 + fm_mode.horizontalAdvance("CALENDRIER") + 14 + QFontMetrics(self.font_msg).horizontalAdvance(head) + 20
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x0, y0, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(x0 + 25, y0 + ISLAND_H / 2), 5, 5)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(x0 + 40, y0, 400, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, "CALENDRIER")
        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x0 + 54 + fm_mode.horizontalAdvance("CALENDRIER"), y0, 600, ISLAND_H),
                   Qt.AlignmentFlag.AlignVCenter, head)

        left = (self.width - CAL_W) / 2
        top = ISLAND_TOP + ISLET + 14
        # ruban du mois
        strip = cal["strip"]
        cell, gap = 26, 4
        fm_s = QFontMetrics(self.font_small)
        label_w = fm_s.horizontalAdvance(cal["month"]) + 16
        sw = 32 + label_w + len(strip) * (cell + gap) - gap
        sx = (self.width - sw) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 230))
        p.drawRoundedRect(QRectF(sx, top, sw, 44), 18, 18)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_small)
        p.drawText(QRectF(sx + 16, top, label_w, 44), Qt.AlignmentFlag.AlignVCenter, cal["month"])
        cx = sx + 16 + label_w
        bold = QFont(self.font_small)
        bold.setBold(True)
        p.setFont(bold)
        for d in strip:
            r = QRectF(cx, top + 9, cell, cell)
            if d["today"]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(BLUE)
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QColor(11, 13, 16))
            elif d["week"]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(42, 48, 58))
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QColor(255, 255, 255))
            else:
                p.setPen(ORANGE if d["kind"] == "a" else BLUE.lighter(125) if d["kind"] else QColor(120, 128, 140))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(d["n"]))
            cx += cell + gap
        top += 56

        if cal.get("detail"):
            self._paint_cal_day(p, left, top, cal["detail"])
        else:
            self._paint_cal_week(p, left, top, cal["days"])

        hint = ("« suivant » / « précédent » : jour · « lundi »… : autre jour · « ferme »" if cal.get("detail") else
                "« suivant » / « précédent » · « jeudi » : le jour en grand · « dix-huit » / « premier janvier » · « ferme »")
        hw = fm_s.horizontalAdvance(hint) + 36
        hy = top + CAL_H - 44 + 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 230))
        p.drawRoundedRect(QRectF((self.width - hw) / 2, hy, hw, 34), 16, 16)
        p.setPen(QColor(200, 205, 214))
        p.setFont(self.font_small)
        p.drawText(QRectF((self.width - hw) / 2, hy, hw, 34), Qt.AlignmentFlag.AlignCenter, hint)
        p.restore()

    def _paint_cal_week(self, p, left, top, days):
        gap = 10
        cw = (CAL_W - 6 * gap) / 7
        ch = CAL_H - 56
        f_name = QFont(self.font_small)
        f_name.setBold(True)
        f_name.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        f_num = QFont("Atkinson Hyperlegible", 34, QFont.Weight.Bold)
        f_time = QFont(self.font_small)
        f_time.setBold(True)
        f_txt = QFont("Atkinson Hyperlegible", 13, QFont.Weight.Bold)
        f_rout = QFont("Atkinson Hyperlegible", 10)
        for i, d in enumerate(days):
            x = left + i * (cw + gap)
            p.save()
            if d["past"]:
                p.setOpacity(0.55)
            p.setPen(QPen(BLUE, 2) if d["today"] or d["focus"] else Qt.PenStyle.NoPen)
            p.setBrush(QColor(31, 42, 68, 245) if d["today"] else QColor(0, 0, 0, 240))
            p.drawRoundedRect(QRectF(x, top, cw, ch), 18, 18)
            inner = cw - 24
            y = top + 14
            p.setPen(QColor(154, 163, 176))
            p.setFont(f_name)
            p.drawText(QRectF(x + 12, y, inner, 18), Qt.AlignmentFlag.AlignLeft, d["name"])
            y += 20
            p.setPen(QColor(255, 255, 255))
            p.setFont(f_num)
            p.drawText(QRectF(x + 12, y, inner, 44), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(d["n"]))
            y += 50
            p.setPen(QColor(38, 42, 49))
            p.drawLine(QPointF(x + 12, y), QPointF(x + cw - 12, y))
            y += 10
            for e in d["items"]:
                p.setPen(ORANGE if e["alarm"] else BLUE.lighter(130))
                p.setFont(f_time)
                p.drawText(QRectF(x + 12, y, inner, 18), Qt.AlignmentFlag.AlignLeft,
                           e["t"] + (" · alarme" if e["alarm"] else ""))
                y += 18
                p.setPen(QColor(255, 255, 255))
                p.setFont(f_txt)
                fm = QFontMetrics(f_txt)
                p.drawText(QRectF(x + 12, y, inner, 20), Qt.AlignmentFlag.AlignLeft,
                           fm.elidedText(e["txt"], Qt.TextElideMode.ElideRight, int(inner)))
                y += 28
            if d["more"]:
                p.setPen(QColor(184, 190, 200))
                p.setFont(f_time)
                p.drawText(QRectF(x + 12, y, inner, 18), Qt.AlignmentFlag.AlignLeft, f"+ {d['more']} autre{'s' if d['more'] > 1 else ''}")
            if d["routine"]:
                p.setPen(QColor(138, 147, 163))
                p.setFont(f_rout)
                flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom) | int(Qt.TextFlag.TextWordWrap)
                p.drawText(QRectF(x + 12, top + ch - 100, inner, 88), flags, "\n".join(d["routine"]))
            p.restore()

    def _paint_cal_day(self, p, left, top, day):
        ch = CAL_H - 56
        p.setPen(QPen(BLUE, 2) if day["today"] else Qt.PenStyle.NoPen)
        p.setBrush(QColor(31, 42, 68, 245) if day["today"] else QColor(0, 0, 0, 240))
        p.drawRoundedRect(QRectF(left, top, CAL_W, ch), 22, 22)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Atkinson Hyperlegible", 26, QFont.Weight.Bold))
        p.drawText(QRectF(left + 28, top + 14, CAL_W - 56, 40), Qt.AlignmentFlag.AlignVCenter, day["title"])
        items = day["items"]
        if not items:
            p.setPen(QColor(184, 190, 200))
            p.setFont(self.font_answer)
            p.drawText(QRectF(left + 28, top + 70, CAL_W - 56, 30), Qt.AlignmentFlag.AlignVCenter, "Rien ce jour-là.")
            return
        per_col = 8
        cols = min(3, (len(items) + per_col - 1) // per_col)
        colw = (CAL_W - 56) / max(cols, 1)
        f_t = QFont("Atkinson Hyperlegible", 17, QFont.Weight.Bold)
        f_x = QFont("Atkinson Hyperlegible", 17)
        for i, e in enumerate(items[:per_col * 3]):
            c, r = divmod(i, per_col)
            x = left + 28 + c * colw
            y = top + 70 + r * 40
            col = ORANGE if e["alarm"] else (QColor(107, 114, 128) if e["routine"] else BLUE)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            if e["alarm"]:
                p.drawRoundedRect(QRectF(x, y + 9, 13, 13), 3, 3)
            else:
                p.drawEllipse(QRectF(x, y + 9, 13, 13))
            p.setPen(QColor(255, 255, 255))
            p.setFont(f_t)
            p.drawText(QRectF(x + 24, y, 80, 32), Qt.AlignmentFlag.AlignVCenter, e["t"])
            p.setFont(f_x)
            fm = QFontMetrics(f_x)
            p.drawText(QRectF(x + 104, y, colw - 116, 32), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(e["txt"], Qt.TextElideMode.ElideRight, int(colw - 116)))

    def _paint_reminder(self, p, kind, data):
        """Carte du rappel déclenché (rouge qui pulse si l'alarme sonne) ou liste des rappels."""
        import time as _t
        pad, top = 22, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        gx = (self.width - (ISLET + ISLET_GAP + REMINDER_W)) / 2
        x = gx + ISLET + ISLET_GAP
        inner = REMINDER_W - 2 * pad
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        title, body, meta = reminder_texts(kind, data)
        font_body = self.font_rem if kind == "current" else self.font_answer
        alarm = kind == "current" and data.get("alarm")
        ringing = kind == "current" and data.get("ringing")
        fm_b, fm_s = QFontMetrics(font_body), QFontMetrics(self.font_small)
        b_rect = fm_b.boundingRect(QRect(0, 0, inner, 1000), flags, body)
        h = min(ANSWER_MAX_H, 46 + b_rect.height() + 44)
        if ringing:      # pulsation : 1 s, entre rouge sombre et rouge vif
            k = 0.5 + 0.5 * math.sin(_t.monotonic() * 2 * math.pi)
            bg = QColor(int(ALARM_RED[0] * (0.6 + 0.4 * k)), ALARM_RED[1], ALARM_RED[2], 245)
        elif alarm:
            bg = QColor(120, 20, 28, 240)
        elif kind == "current":
            bg = QColor(28, 38, 70, 245)       # bleu nuit : se distingue du noir habituel
        else:
            bg = QColor(0, 0, 0, 240)
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(x, top, REMINDER_W, h), 22, 22)
        bell = self.icons.get("bell")
        if bell is not None:
            bell.render(p, QRectF(x + pad, top + 11, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(x + pad + ICON + 10, top, inner, 46), Qt.AlignmentFlag.AlignVCenter, title)
        p.setFont(font_body)
        p.save()
        p.setClipRect(QRectF(x + pad, top + 46, inner, max(0, h - 46 - 36)))
        p.drawText(QRectF(x + pad, top + 46, inner, b_rect.height()), flags, body)
        p.restore()
        p.setPen(QColor(255, 255, 255, 170))
        p.setFont(self.font_small)
        p.drawText(QRectF(x + pad, top + h - 30, inner, 22), Qt.AlignmentFlag.AlignVCenter,
                   fm_s.elidedText(meta, Qt.TextElideMode.ElideRight, inner))
        p.restore()

    def _paint_discord(self, p, islet_x, y):
        """Pastille noire à gauche de l'îlot, icônes rouges ; ne s'estompe jamais, comme le logo.
        La pastille du prochain rappel se place encore à sa gauche."""
        if not self.discord:
            return
        pad, gap = 12, 6
        w = 2 * pad + len(self.discord) * ICON + (len(self.discord) - 1) * gap
        x = islet_x - ISLET_GAP - w
        top = y + (ISLET - ISLAND_H) / 2
        p.save()
        p.setOpacity(1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, top, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        ix = x + pad
        for name in self.discord:
            r = self.icons.get(name)
            if r is not None:
                r.render(p, QRectF(ix, top + (ISLAND_H - ICON) / 2, ICON, ICON))
            ix += ICON + gap
        p.restore()

    def _paint_islet(self, p, x, y):
        """Logo à sa place, ou en cours d'animation (« iris heure ») : il grossit vers la gauche en tournant
        jusqu'à couvrir l'île et la fiche de l'heure, son bord droit restant collé à l'île."""
        k, angle = clock_anim(getattr(self, "anim_now", 0.0), self.clk_start, self.clk_end)
        size = ISLET + (CLOCK_BIG - ISLET) * k
        right = x + ISLET
        bars_top = ISLAND_TOP + (ISLET - ISLAND_H) / 2
        cy = (y + ISLET / 2) + ((bars_top + CLOCK_BIG / 2) - (y + ISLET / 2)) * k
        self._paint_discord(p, right - size, y)
        p.save()
        p.translate(right - size / 2, cy)
        p.rotate(angle)
        p.scale(size / ISLET, size / ISLET)
        p.translate(-ISLET / 2, -ISLET / 2)
        self._draw_logo(p, 0, 0)
        p.restore()

    def _draw_logo(self, p, x, y):
        """Disque clair à fin contour sombre. La main, agrandie et centrée sur l'œil, est découpée
        par le cercle : le bout des doigts sort du cadre et n'est pas dessiné."""
        circle = QRectF(x + 1, y + 1, ISLET - 2, ISLET - 2)
        # centrée sur l'œil à l'horizontale ; le bas de la paume posé sur le bas du cercle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(245, 245, 240))
        p.drawEllipse(circle)
        pm = self.logos.get(self.logo)
        if pm is not None:
            pw = ISLET * EYE_IN_ISLET / EYE_W                   # largeur affichée de l'image
            ph = pw * pm.height() / pm.width()
            cx = x + ISLET / 2
            clip = QPainterPath()
            clip.addEllipse(circle)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(QRectF(cx - EYE_AT[0] * pw, circle.bottom() - ph, pw, ph), pm, QRectF(pm.rect()))
            p.restore()
        col, width = self.ring
        p.setPen(QPen(col, width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(circle.adjusted(width / 2 - 1, width / 2 - 1, 1 - width / 2, 1 - width / 2))
