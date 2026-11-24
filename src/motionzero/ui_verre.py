"""Verre plein écran transparent aux clics, boutons STOP / œil / réparer, capteur de touches (découpé de ui.py, #52)."""
import ctypes
import os as _os
import time as _time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .ui_accueil_fen import _u32
from .ui_ile import BAND_HALF_W, GHOST_S, _ICON_DIR, _IslandPainter, _ghost_box, gauge_geometry, ghost_geometry, paint_subs, paint_volume, subs_rect, subs_text, volume_rect


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
