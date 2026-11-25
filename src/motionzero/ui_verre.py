"""Verre plein écran transparent aux clics, boutons STOP / œil / réparer, capteur de touches (découpé de ui.py, #52).
"""
import os as _os
import time as _time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .ui_ile import BAND_HALF_W, GHOST_S, _ICON_DIR, _IslandPainter, _ghost_box, gauge_geometry, ghost_geometry, paint_subs, paint_volume, subs_rect, subs_text, volume_rect
from .ui_boutons import (EyeButton, HALO_W, KeySink, LOUPE_D, LOUPE_GAP, LOUPE_ZOOM, RING_R, RING_W, RepairButton, STOP_HAND_PAD, STOP_MARGIN, STOP_RED, STOP_SIZE, StopButton, _GWL_EXSTYLE, _WDA_EXCLUDEFROMCAPTURE, _WS_EX_LAYERED, _WS_EX_NOACTIVATE, _WS_EX_TOOLWINDOW, _WS_EX_TOPMOST, _WS_EX_TRANSPARENT, _u32, apply_overlay_style, set_capture_visible)  # noqa: F401


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
        self.island = _IslandPainter(self.width(), self.height()) if role == "ui" else None   # île Dot Iris
        self.subs = None          # « iris traducteur » : {"lines", "error"} ou None
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
            subs = st.get("subs")
            if subs != self.subs:
                for s in (self.subs, subs):
                    if s is not None:
                        self.update(subs_rect(self.width(), self.height()).toAlignedRect().adjusted(-4, -4, 4, 4))
                self.subs = subs
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
        c, r = g["hand"].center(), RING_R                     # le curseur lui-même, déplacé dans la jauge
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 150), HALO_W))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 90), RING_W))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(c, 5, 5)

    def _paint_ghost(self, p):
        hand, ctr, r, band = self.ghost
        p.setBrush(Qt.BrushStyle.NoBrush)
        for col, w in ((QColor(0, 0, 0, 110), 4), (QColor(220, 220, 220, 170), 2)):   # zone du centre
            p.setPen(QPen(col, w, Qt.PenStyle.DashLine))
            if band:                          # « défile » : amener la main entre les deux traits
                for yy in (ctr.y() - r, ctr.y() + r):
                    p.drawLine(QPointF(ctr.x() - BAND_HALF_W, yy), QPointF(ctr.x() + BAND_HALF_W, yy))
            else:
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
        if self.subs is not None:
            paint_subs(p, subs_rect(self.width(), self.height()), subs_text(self.subs))
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


# --- Étape 4 : l'île Dot Iris (en haut au centre, dans le verre) ------------------------------------
