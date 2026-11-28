"""Verre plein écran transparent aux clics, boutons STOP / œil / réparer, capteur de touches (découpé de ui.py, #52) : constantes et fonctions (1/1, découpé de ui_verre.py, #52)."""
import ctypes
import os as _os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .ui_accueil_fen import _u32
from .ui_ile import _ICON_DIR


_GWL_EXSTYLE = -20
_WS_EX_LAYERED, _WS_EX_TRANSPARENT = 0x80000, 0x20
_WS_EX_NOACTIVATE, _WS_EX_TOOLWINDOW, _WS_EX_TOPMOST = 0x08000000, 0x80, 0x8
_WDA_EXCLUDEFROMCAPTURE = 0x11
_u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
_u32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_HWND_TOPMOST = ctypes.c_void_p(-1)
_SWP_KEEP = 0x0001 | 0x0002 | 0x0010 | 0x0200   # ni taille, ni position, ni activation, ni ordre du propriétaire
KEEP_ON_TOP_MS = 1500   # Windows peut faire redescendre l'overlay : on le remonte à ce rythme

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
    ex |= _WS_EX_LAYERED | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
    if click_through:
        ex |= _WS_EX_TRANSPARENT
    _u32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex)
    set_capture_visible(widget, in_captures)
    raise_topmost([widget])


def raise_topmost(widgets):
    """Remet les fenêtres visibles au-dessus de tout, sans focus. Le style WS_EX_TOPMOST seul ne suffit pas :
    Windows peut les faire redescendre parmi les fenêtres normales (vu le 28/11 : VS Code devant l'île).
    Renvoie le nombre de fenêtres remontées ; un échec n'arrête jamais Iris."""
    n = 0
    for w in widgets:
        try:
            if not w.isVisible():
                continue
            if _u32.SetWindowPos(ctypes.c_void_p(int(w.winId())), _HWND_TOPMOST, 0, 0, 0, 0, _SWP_KEEP):
                n += 1
        except Exception:                  # fenêtre détruite, appel Windows refusé : on réessaie au tour suivant
            pass
    return n


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
