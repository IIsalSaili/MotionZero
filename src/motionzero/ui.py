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
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .accueil import HOME_TITLE, conso_line

__all__ = ["Bridge", "EyeButton", "GlassOverlay", "KeySink", "PreviewWindow", "QApplication", "StopButton",
           "set_capture_visible"]


class Bridge(QObject):
    frame = Signal(object)   # image BGR (numpy) déjà dessinée par overlay.render
    state = Signal(object)   # état pour le verre : curseur, progression, main perdue
    stop_hover = Signal(float)  # survol du bouton STOP par la main (0..1)
    done = Signal()          # le moteur s'est arrêté
    stats = Signal(object)   # mesures de consommation (ligne du bas de la page d'accueil)
    home = Signal(object)    # contenu de la page d'accueil (accueil.home_view)
    repair_done = Signal()   # réparation du son finie (fil « reparation » -> bouton, dans le fil Qt)
    pointer = Signal(str)    # souris à la main / à la tête (changé à la voix) -> bouton de l'accueil
    quiet = Signal(str)      # choix « voix basse » enregistré -> bouton de l'accueil
    iris_volume = Signal(float)  # volume des sons d'Iris choisi -> bouton de l'accueil


def pointer_button_text(pointer):
    """Texte du bouton de l'accueil. Pur : testable."""
    return "Souris : tête  ·  passer à la main" if pointer == "tete" else "Souris : main  ·  passer à la tête"


def quiet_button_text(choice):
    """Texte du bouton « voix basse » de l'accueil. Pur : testable."""
    return {"oui": "Voix basse : toujours", "non": "Voix basse : jamais"}.get(
        choice, "Voix basse : le soir (22 h - 7 h)")


def volume_button_text(volume):
    """Texte du bouton « volume d'Iris » de l'accueil. Pur : testable."""
    return f"Volume d'Iris : {round(volume * 100)} %"


# --- Page d'accueil : mise en page A « Tableau calme », DA Dot Iris (issue #35) ----------------------------------
# Le contenu vient d'accueil.home_view (calculé dans la boucle) ; ici, seulement le dessin.
HOME = {"fond": "#0B0B0E", "surface": "#17171C", "bord": "#2A2A32", "texte": "#F2F2F5", "texte2": "#A6A6B0",
        "off": "#6E6E78", "lecture": "#B48CFF", "souris": "#F5A524", "chrome": "#6F9BF5", "ok": "#34C759",
        "erreur": "#FF5A5F"}
MODE_COLORS_HOME = {"CHROME": HOME["chrome"], "LECTURE": HOME["lecture"], "NEUTRE": HOME["off"], "PAUSE": HOME["off"]}
TONE_COLORS = {"listen": HOME["ok"], "busy": HOME["lecture"], "off": HOME["off"], "idle": HOME["texte"]}
SENSOR_COLORS = {"ok": HOME["ok"], "off": HOME["souris"], "idle": HOME["off"], "fail": HOME["erreur"]}
_FONT = "'Atkinson Hyperlegible'"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def now_html(title, rows):
    """Bloc « Ici, maintenant » en texte riche : effet à gauche, mot à dire en vert. Pur : testable."""
    lines = "".join(
        f"<tr><td style='padding:3px 12px 3px 0'>{_esc(what)}</td>"
        f"<td style='padding:3px 0;color:{HOME['ok']};font-weight:bold' align='right'>{_esc(word)}</td></tr>"
        for word, what in rows)
    return (f"<div style='color:{HOME['chrome']};font-size:12pt;font-weight:bold;letter-spacing:1px'>"
            f"{_esc(title.upper())}</div><table width='100%' style='font-size:13pt'>{lines}</table>")


def sensors_html(items):
    """Pastilles des capteurs et services. Pur : testable."""
    out = []
    for name, state, detail in items:
        c = SENSOR_COLORS.get(state, HOME["off"])
        d = f" <span style='color:{HOME['texte2']}'>{_esc(detail)}</span>" if detail else ""
        out.append(f"<span style='color:{c}'>●</span> {_esc(name)}{d}")
    return "&nbsp;&nbsp;&nbsp;".join(out)


def last_html(items):
    """Dernières commandes : vert compris, rouge refusé, avec leur âge. Pur : testable."""
    if not items:
        return f"<span style='color:{HOME['off']}'>Aucune commande récente</span>"
    out = []
    for label, ok, age in items:
        c, sign = (HOME["ok"], "✓") if ok else (HOME["erreur"], "✗")
        out.append(f"<span style='color:{c}'>{sign} {_esc(label)}</span>"
                   f"<span style='color:{HOME['texte2']}'> · {age:.0f} s</span>")
    return "&nbsp;&nbsp;&nbsp;&nbsp;".join(out)


def _pill_style(bg, fg, border=None, radius=28):
    return (f"QPushButton {{ background: {bg}; color: {fg}; border: 3px solid {border or bg}; border-radius: {radius}px;"
            f" font: bold 14pt {_FONT}; padding: 0 16px; }}"
            f"QPushButton:hover {{ border-color: {HOME['texte']}; }}")


class PreviewWindow(QWidget):
    closed = Signal()
    pointer_clicked = Signal()                 # « main / tête » : traité par la boucle principale (jamais ici)
    quiet_clicked = Signal()                   # « voix basse » : idem
    volume_clicked = Signal()                  # « volume d'Iris » : idem

    def __init__(self, pointer="main", quiet="auto", volume=0.5):
        super().__init__()
        load_fonts()
        self.setWindowTitle(HOME_TITLE)
        self.setStyleSheet(f"PreviewWindow {{ background: {HOME['fond']}; }}"
                           f"QLabel {{ color: {HOME['texte']}; font-family: {_FONT}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.pointer = pointer

        # bande du haut : logo, état, mode, rappel des mots d'aide
        bar = QWidget()
        bar.setObjectName("bar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setStyleSheet("#bar { background: #000; border-radius: 40px; }")
        bar.setFixedHeight(80)
        self.logo = HomeLogo()                 # le même logo que l'île, disque clair
        self.state_lbl = QLabel("Démarrage…")
        self.state_lbl.setStyleSheet(f"font: bold 24pt {_FONT};")
        self.mode_lbl = QLabel()
        self.mouse_lbl = QLabel("SOURIS")
        self.mouse_lbl.setStyleSheet(f"background: {HOME['souris']}; color: {HOME['fond']}; border-radius: 14px;"
                                     f" padding: 4px 14px; font: bold 12pt {_FONT}; letter-spacing: 2px;")
        self.mouse_lbl.hide()
        hint = QLabel(f"Toutes les commandes : <b style='color:{HOME['ok']}'>iris aide</b>"
                      f" &nbsp;·&nbsp; doc : <b style='color:{HOME['ok']}'>iris guide</b>")
        hint.setStyleSheet(f"color: {HOME['texte2']}; font-size: 12pt;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 0, 28, 0)
        bl.setSpacing(18)
        for w in (self.logo, self.state_lbl, self.mode_lbl, self.mouse_lbl):
            bl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        bl.addStretch(1)
        bl.addWidget(hint)

        # gauche : la caméra seule (sans texte dessus), puis les capteurs
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setText("Démarrage de la caméra…")
        self.label.setMinimumSize(480, 360)
        # l'image suit la taille de la zone, jamais l'inverse (sinon la fenêtre grandit à chaque image)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.label.setStyleSheet(f"background: #060608; border-radius: 16px; color: {HOME['texte2']}; font-size: 14pt;")
        self.sensors_lbl = QLabel()
        self.sensors_lbl.setWordWrap(True)
        self.sensors_lbl.setStyleSheet("font-size: 12pt;")
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self.label, 1)
        left.addWidget(self.sensors_lbl)

        # droite : main / tête, ce qui marche ici, voix basse et volume
        self.main_btn = QPushButton("MAIN")
        self.head_btn = QPushButton("TÊTE")
        self.quiet_btn = QPushButton(quiet_button_text(quiet))
        self.quiet_btn.setToolTip("Iris accepte une voix plus faible. Clic : le soir / toujours / jamais")
        self.volume_btn = QPushButton(volume_button_text(volume))
        self.volume_btn.setToolTip("Sons d'Iris seulement (pas le volume de Windows). Clic : 30 / 50 / 70 / 100 %")
        for b in (self.main_btn, self.head_btn, self.quiet_btn, self.volume_btn):
            b.setMinimumHeight(64)             # grande cible (clic à la main ou à la tête)
            # jamais au clavier : avec le focus, une touche Espace (envoyée par Iris, la dictée, un réveil…)
            # « cliquait » le bouton sans que personne ne l'ait touché
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for b in (self.quiet_btn, self.volume_btn):
            b.setStyleSheet(_pill_style("#000", HOME["texte"], "#555"))
        self.main_btn.clicked.connect(lambda: self._choose_pointer("main"))
        self.head_btn.clicked.connect(lambda: self._choose_pointer("tete"))
        self.quiet_btn.clicked.connect(self.quiet_clicked.emit)
        self.volume_btn.clicked.connect(self.volume_clicked.emit)
        ptr = QHBoxLayout()
        ptr.setSpacing(16)
        ptr.addWidget(self.main_btn)
        ptr.addWidget(self.head_btn)
        self.now_lbl = QLabel()
        self.now_lbl.setWordWrap(True)
        self.now_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.now_lbl.setStyleSheet(f"background: {HOME['surface']}; border-radius: 16px; padding: 16px 20px;")
        right_w = QWidget()
        right_w.setFixedWidth(400)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(14)
        right.addLayout(ptr)
        right.addWidget(self.now_lbl, 1)
        right.addWidget(self.quiet_btn)
        right.addWidget(self.volume_btn)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addLayout(left, 1)
        body.addWidget(right_w)

        # bas : consommation sur une ligne, dernières commandes
        self.conso_lbl = QLabel(conso_line(None))
        self.conso_lbl.setStyleSheet(f"color: {HOME['texte2']}; font-size: 11pt;")
        self.last_lbl = QLabel(last_html([]))
        self.last_lbl.setStyleSheet("font-size: 12pt;")
        foot = QHBoxLayout()
        foot.setContentsMargins(8, 0, 8, 0)
        foot.addWidget(self.conso_lbl)
        foot.addStretch(1)
        foot.addWidget(self.last_lbl)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 16)
        lay.setSpacing(18)
        lay.addWidget(bar)
        lay.addLayout(body, 1)
        lay.addLayout(foot)
        self._home = None
        self.set_pointer(pointer)
        self.set_home({"state": "Démarrage…", "tone": "idle", "mode": "NEUTRE", "mouse": False,
                       "now_title": "Maintenant", "now_rows": [], "sensors": [], "last": []})
        self.resize(1280, 760)
        self.visible_flag = True   # lu par le moteur : réduite, l'aperçu n'est plus dessiné

    def _choose_pointer(self, pointer):
        if pointer == self.pointer:
            return
        self.set_pointer(pointer)
        self.pointer_clicked.emit()

    def set_pointer(self, pointer):
        """Choix courant (aussi changé à la voix) : la cible choisie est pleine, l'autre en contour."""
        self.pointer = pointer
        on, off = _pill_style(HOME["souris"], HOME["fond"]), _pill_style(HOME["surface"], HOME["texte"], HOME["bord"])
        self.main_btn.setStyleSheet(on if pointer != "tete" else off)
        self.head_btn.setStyleSheet(on if pointer == "tete" else off)
        self.main_btn.setToolTip("Dire : iris main")
        self.head_btn.setToolTip("Dire : iris tête")

    def set_volume(self, volume):
        self.volume_btn.setText(volume_button_text(volume))

    def set_quiet(self, choice):
        self.quiet_btn.setText(quiet_button_text(choice))

    def set_stats(self, s):
        self.conso_lbl.setText(conso_line(s))

    def set_home(self, v):
        """Contenu calculé par accueil.home_view ; on ne redessine que ce qui a changé."""
        if v == self._home:
            return
        old, self._home = self._home or {}, v
        if (v.get("state"), v.get("tone")) != (old.get("state"), old.get("tone")):
            self.state_lbl.setText(v.get("state", ""))
            self.state_lbl.setStyleSheet(f"font: bold 24pt {_FONT}; color: {TONE_COLORS.get(v.get('tone'), HOME['texte'])};")
        if v.get("mode") != old.get("mode"):
            m = v.get("mode", "")
            self.mode_lbl.setText(m)
            self.mode_lbl.setStyleSheet(f"background: {MODE_COLORS_HOME.get(m, HOME['off'])}; color: {HOME['fond']};"
                                        f" border-radius: 14px; padding: 4px 14px; font: bold 12pt {_FONT};"
                                        f" letter-spacing: 2px;")
        self.mouse_lbl.setVisible(bool(v.get("mouse")))
        if (v.get("now_title"), v.get("now_rows")) != (old.get("now_title"), old.get("now_rows")):
            self.now_lbl.setText(now_html(v.get("now_title", ""), v.get("now_rows", [])))
        if v.get("sensors") != old.get("sensors"):
            self.sensors_lbl.setText(sensors_html(v.get("sensors", [])))
        if v.get("last") != old.get("last"):
            self.last_lbl.setText(last_html(v.get("last", [])))

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
        pix = QPixmap.fromImage(qimg)
        box = self.label.size()
        if box.width() > 0 and box.height() > 0:
            pix = pix.scaled(box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        self.label.setPixmap(pix)

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
_FONT_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                          "assets", "fonts")
ISLAND_TOP = 12          # px depuis le haut de l'écran
ANSWER_W = 560           # largeur de l'île agrandie pour une réponse de Claude
ANSWER_MAX_H = 640      # 3 phrases longues tiennent ; au-delà, le texte est coupé proprement
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
PANEL_W = 452            # « iris candidature » : panneau à droite (maquette A1, 21/11)
PANEL_MARGIN = 16
PANEL_BOTTOM = 64        # au-dessus de la barre des tâches
CAND = QColor(124, 212, 184)   # vert d'eau du mode candidature
CAL_W = 1060             # calendrier : 7 cartes
CAL_H = 470
HELP_W = 1060            # « iris aide »
HELP_H = 800
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


def clock_anim(now, start, end, motion=True):
    """(agrandissement 0..1, angle en degrés) du logo pendant « iris heure ». Pur : testable.
    Aller : rotation vers la gauche en grossissant ; retour : vers la droite en rapetissant."""
    if start is None:
        return 0.0, 0.0
    if not motion:                       # effets d'animation coupés dans Windows : changement immédiat
        return (1.0, 0.0) if end is None else (0.0, 0.0)
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
    if st.get("plan"):                       # « iris instruction » : ce qu'Iris va faire, avant de le faire
        return "plan", st["plan"]
    if rem.get("calendar"):
        return "calendar", rem["calendar"]
    if rem.get("list"):
        return "list", rem["list"]
    return None


def reminder_texts(kind, data):
    """(titre, texte, ligne du bas) de la carte des rappels. Pur : testable."""
    if kind == "list":
        return ("RAPPELS À VENIR", "\n".join(data), "« Iris rappel » pour en ajouter ou en supprimer")
    if kind == "plan":
        return (data["title"], "\n".join(data["lines"]),
                data.get("meta") or "« envoie » dans les 10 s : faire · sinon annulé · « stop » : arrêter")
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


SUBS_W_FRAC = 0.7       # bandeau des sous-titres : 70 % de la largeur de l'écran
SUBS_H = 110
SUBS_BOTTOM = 70        # px au-dessus du bas (laisse la barre des tâches et les commandes de lecture)


def subs_rect(w, h):
    bw = w * SUBS_W_FRAC
    return QRectF((w - bw) / 2, h - SUBS_BOTTOM - SUBS_H, bw, SUBS_H)


def subs_text(subs):
    """Texte du bandeau : l'erreur, les 2 dernières phrases, ou None (rien entendu : bandeau caché). Pur."""
    if subs is None:
        return None
    if subs.get("error"):
        return subs["error"]
    return "\n".join(subs.get("lines") or []) or None


def paint_subs(p, box, text):
    """Même style que l'île : noir opaque, blanc, Atkinson. Rien à dire : rien de dessiné."""
    if not text:
        return
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 215))
    p.drawRoundedRect(box, 18, 18)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Atkinson Hyperlegible", 19, QFont.Weight.Bold))
    p.drawText(box.adjusted(24, 10, -24, -10),
               int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text)
    p.restore()


MIN_PT = 11              # plus petit que ça n'est plus lisible : au-delà, la carte s'agrandit (jusqu'au maximum)


def fit_font(font, text, width, max_h=None, min_pt=MIN_PT):
    """Police la plus grande (jusqu'à `font`) qui fait tenir le texte entier : une ligne si max_h est None,
    sinon en plusieurs lignes dans max_h. Jamais de texte coupé tant que min_pt suffit (demande du 17/11)."""
    f = QFont(font)
    flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
    while True:
        fm = QFontMetrics(f)
        if max_h is None:
            fits = fm.horizontalAdvance(text) <= width
        else:
            fits = fm.boundingRect(QRect(0, 0, int(width), 100000), flags, text).height() <= max_h
        if fits or f.pointSizeF() <= min_pt:
            return f
        f.setPointSizeF(f.pointSizeF() - 1)


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
    if g and len(g) == 4:                     # « défile » : bande horizontale à atteindre (seule la hauteur compte)
        x, y, r, cy = g
        return (QPointF(x / dpr, y / dpr), QPointF(x / dpr, cy / dpr), r / dpr, True)
    if not g or not st.get("arming"):
        return None
    cur = st.get("cursor")
    x, y, r = g
    ctr = QPointF(cur[0] / dpr, cur[1] / dpr) if cur is not None else QPointF(x / dpr, y / dpr)
    return (QPointF(x / dpr, y / dpr), ctr, r / dpr, False)


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


BAND_HALF_W = 300       # « défile » : demi-largeur des traits de la bande du centre, autour de la main


def _ghost_box(g):
    hand, ctr, r, band = g
    m = GHOST_S / 2 + 12
    a = QRect(int(hand.x() - m), int(hand.y() - m), int(2 * m), int(2 * m))
    if band:
        b = QRect(int(ctr.x() - BAND_HALF_W - 6), int(ctr.y() - r - 6), int(2 * BAND_HALF_W + 12), int(2 * r + 12))
        return a.united(b)
    b = QRect(int(ctr.x() - r - 6), int(ctr.y() - r - 6), int(2 * r + 12), int(2 * r + 12))
    return a.united(b)


def islet_logo(st, blinking):
    """Nom du logo à afficher. Pur : testable. Toujours le logo noir classique ; le mode se lit au cercle."""
    return "neutre_ferme" if blinking else "neutre"


RING_DEFAULT = QColor(0, 0, 0, 200)
RING_BY_MODE = {"SOURIS": ORANGE, "CHROME": BLUE}
GREEN = QColor(52, 199, 89)
RING_BLINK_S = 0.17      # commande comprise : 2 éclats verts en 0,5 s (moins de 3 par seconde, WCAG 2.3.1)


def windows_animations():
    """Réglage Windows « Effets d'animation » (#11). Illisible : on suppose qu'il est allumé."""
    try:
        on = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):   # SPI_GETCLIENTAREAANIMATION
            return bool(on.value)
    except Exception:
        pass
    return True


def islet_ring(st, age, motion=True):
    """Couleur et épaisseur du cercle autour de la main. Pur : testable.
    Orange quand la souris est allumée (quel que soit le mode), bleu en Chrome ; une commande comprise le fait
    clignoter en vert."""
    if st.get("ok_flash") and (not motion or int(age / RING_BLINK_S) % 2 == 0):   # sans animation : vert fixe
        return GREEN, 3.5
    col = ORANGE if st.get("mouse") else RING_BY_MODE.get(st.get("mode"))
    return (col, 3.5) if col is not None else (RING_DEFAULT, 2.0)


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


def island_text(st):
    """(mode affiché, message ou None, actif ?) d'après l'état envoyé par le moteur. Pur : testable."""
    mode = MODE_NAMES.get(st.get("mode"), st.get("mode") or "")
    if st.get("mouse"):
        mode = "SOURIS" if mode in ("NEUTRE", "") else f"{mode} · SOURIS"   # la souris s'ajoute au mode
    if st.get("focus"):
        mode = f"{mode} · FOCUS" if mode else "FOCUS"
    if st.get("bypass"):
        mode = f"{mode} · BYPASS" if mode else "BYPASS"
    if st.get("candidature"):
        mode = f"{mode} · CANDIDATURE" if mode else "CANDIDATURE"
    if st.get("dragging"):                    # « agrippe » : bouton tenu, visible tant qu'il l'est (19/11)
        mode = f"{mode} · AGRIPPE" if mode else "AGRIPPE"
    qa = st.get("qa") or {}
    if qa.get("phase") == "listening":
        return mode, "Pose ta question…", True
    if qa.get("phase") == "thinking":
        return mode, "Iris réfléchit…", True
    if qa.get("phase") == "searching":
        return mode, "Iris cherche sur internet…", True
    if qa.get("phase") == "answer":
        return mode, "Iris répond", True
    if qa.get("phase") == "error":
        return mode, "Question : échec", True
    if st.get("dictating"):
        return mode, "Claude t'écoute", True
    if st.get("typing"):
        return mode, "Dicte ton texte…", True
    if st.get("confirming"):
        pending = (st.get("reminders") or {}).get("pending")
        return mode, (f"{pending} — dis ENVOIE" if pending else "Dis ENVOIE ou ANNULE"), True
    if st.get("listening"):
        return mode, "Iris écoute…", True
    head = st.get("pointer") == "tete"
    if st.get("lost") and st.get("mouse"):
        return mode, "Visage non détecté" if head else "Main non détectée", True
    if st.get("arming"):
        return mode, "Tête de face pour démarrer" if head else "Main au centre pour démarrer", True
    toast, age = st.get("toast"), st.get("toast_age", 1e9)
    if toast and age <= TOAST_S:
        return mode, toast, True
    return mode, None, False


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


class _IslandPainter:
    """Dessine l'île dans le verre. Ne garde que ce qu'il faut pour l'estomper au repos."""

    def __init__(self, width, height=1080):
        load_fonts()
        self.height = height
        self.panel = None
        self.panel_gone = False
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
        self.motion = windows_animations()   # lu au démarrage

    def rect(self):
        w = max(ISLAND_MAX_W + 2 * (ISLET + ISLET_GAP) + 2 * 120, CAL_W + 40)   # + pastille Discord / calendrier
        h = max(ISLET + ANSWER_MAX_H + 8, ISLET + 14 + 56 + CAL_H + 10, ISLET + 14 + HELP_H + 10)
        x = int((self.width - w) // 2)
        if getattr(self, "quota", None) or getattr(self, "quota_gone", False):   # pastille du quota (ou à effacer)
            w, x = w + x, 0
            self.quota_gone = False
        r = QRect(x, ISLAND_TOP - 4, int(w), h)
        if getattr(self, "panel", None) or getattr(self, "panel_gone", False):   # panneau candidature (ou à effacer)
            self.panel_gone = False
            r = r.united(QRect(int(self.width - PANEL_W - 2 * PANEL_MARGIN), 0, PANEL_W + 2 * PANEL_MARGIN,
                               int(self.height)))
        return r

    def update(self, st, now):
        mode, msg, active = island_text(st)
        qa = st.get("qa") or {}
        self.qa = qa if qa.get("phase") in ("answer", "error") else None
        self.rem = reminder_view(st)
        self.help = st.get("help")
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
        if self.clk_end is not None and now - self.clk_end >= (CLOCK_ANIM_S if self.motion else 0.0):
            self.clk_start = self.clk_end = None               # le logo a repris sa place
        if clock:
            self.next_rem = clock
        elif self.clk_start is None:
            self.next_rem = None
        self.anim_now = now
        if self.next_rem:
            active = True
        if self.rem or self.help:
            active = True
        rem_key = (self.rem[0], str(self.rem[1])) if self.rem else (("help", str(self.help["now"])) if self.help else None)
        q = st.get("quota")                    # [(« 5 h », « 40 % · reset 22h59 »), (« Semaine », …)] si allumé
        if getattr(self, "quota", None) and not q:
            self.quota_gone = True             # masquée : repeindre le coin gauche une fois pour l'effacer
        self.quota = tuple(q) if q else None
        panel = st.get("cand_panel")
        if getattr(self, "panel", None) and not panel:
            self.panel_gone = True             # mode éteint : repeindre la droite une fois pour l'effacer
        self.panel = panel
        if panel:
            active = True
        content = (mode, msg, (qa.get("phase"), qa.get("answer"), int(qa.get("left", 0))) if self.qa else None,
                   rem_key, self.next_rem, tuple(self.timer_pills), self.quota, repr(panel) if panel else None)
        if content != self.content:
            self.content, self.last_change = content, now
        if st.get("ok_flash"):
            self.last_change = now
        # clignement : 0,5 s, à intervalle irrégulier
        if self.motion and now >= self.next_blink:
            self.blink_until = now + BLINK_S
            self.next_blink = now + _random.uniform(*BLINK_EVERY)
        logo = islet_logo(st, now < self.blink_until)
        if st.get("ok_flash"):
            self.flash_t0 = now if self.flash_t0 is None else self.flash_t0
        else:
            self.flash_t0 = None
        ring = islet_ring(st, now - self.flash_t0 if self.flash_t0 is not None else 0.0, self.motion)
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
        moving = self.motion and self.clk_start is not None and (self.clk_end is not None or now - self.clk_start < CLOCK_ANIM_S)
        ringing = bool(self.rem and self.rem[0] == "current" and self.rem[1].get("ringing"))
        return moving or (ringing and self.motion)

    def paint(self, p):
        if not self.content:
            return
        self._paint_main(p)
        if getattr(self, "quota", None):
            self._paint_quota(p, self.quota)
        if getattr(self, "panel", None):
            self._paint_cand_panel(p, self.panel)

    def _wrap(self, p, font, color, x, y, w, text, max_h=10000):
        """Texte sur plusieurs lignes ; renvoie la hauteur utilisée (bornée à max_h)."""
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        h = min(QFontMetrics(font).boundingRect(QRect(0, 0, int(w), 100000), flags, text).height(), max_h)
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(x, y, w, h), flags, text)
        return h

    def _paint_cand_panel(self, p, pn):
        """« iris candidature » : panneau à droite, le site reste visible à gauche (maquette A1)."""
        big = QFont("Atkinson Hyperlegible", 20, QFont.Weight.Bold)
        num = QFont("Atkinson Hyperlegible", 18, QFont.Weight.Bold)
        word = QFont("Atkinson Hyperlegible", 15, QFont.Weight.Bold)
        small, msgf = self.font_small, self.font_msg
        grey, light, white = QColor(166, 166, 176), QColor(201, 201, 209), QColor(242, 242, 245)
        surf, chip = QColor(23, 23, 28), QColor(36, 36, 43)
        x0 = self.width - PANEL_W - PANEL_MARGIN
        h = self.height - PANEL_MARGIN - PANEL_BOTTOM
        pad = 24
        x, inner = x0 + pad, PANEL_W - 2 * pad
        p.save()
        p.setPen(QColor(42, 42, 50))
        p.setBrush(QColor(11, 11, 14, 245))
        p.drawRoundedRect(QRectF(x0, PANEL_MARGIN, PANEL_W, h), 18, 18)
        y = PANEL_MARGIN + 22
        # en-tête
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(CAND)
        p.drawEllipse(QPointF(x + 5, y + 12), 5, 5)
        p.setPen(white)
        p.setFont(self.font_mode)
        p.drawText(QRectF(x + 18, y, 220, 24), Qt.AlignmentFlag.AlignVCenter, "CANDIDATURE")
        p.setPen(grey)
        p.setFont(small)
        status = pn.get("status") or ""
        if pn.get("busy"):
            status = "CVGEN travaille…"
        p.drawText(QRectF(x, y, inner, 24), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), status)
        y += 40
        # chiffres
        tiles = pn.get("tiles") or []
        if tiles:
            tw = (inner - 6 * (len(tiles) - 1)) / len(tiles)
            for k, (n, lbl, on) in enumerate(tiles):
                r = QRectF(x + k * (tw + 6), y, tw, 60)
                p.setPen(CAND if on else Qt.PenStyle.NoPen)
                p.setBrush(surf)
                p.drawRoundedRect(r, 8, 8)
                p.setPen(white)
                p.setFont(num)
                p.drawText(QRectF(r.x(), r.y() + 6, tw, 28), Qt.AlignmentFlag.AlignCenter, str(n))
                p.setPen(grey)
                p.setFont(small)
                p.drawText(QRectF(r.x(), r.y() + 34, tw, 20), Qt.AlignmentFlag.AlignCenter, lbl)
            y += 76
        # bas : les mots à dire (fixés en bas du panneau)
        words = (pn.get("words") or [])[:4]
        rows = (len(words) + 1) // 2
        bottom = PANEL_MARGIN + h - 22
        foot_y = bottom - 20
        grid_h = rows * 48 + max(rows - 1, 0) * 8
        grid_y = foot_y - 12 - grid_h
        p.setPen(QColor(138, 142, 154))
        p.setFont(small)
        p.drawText(QRectF(x, foot_y, inner, 20), Qt.AlignmentFlag.AlignCenter, pn.get("foot") or "")
        if words:
            p.drawText(QRectF(x, grid_y - 24, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Tu peux dire")
            ww = (inner - 8) / 2
            for k, w in enumerate(words):
                r = QRectF(x + (k % 2) * (ww + 8), grid_y + (k // 2) * 56, ww, 48)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(CAND if k == 0 else chip)
                p.drawRoundedRect(r, 10, 10)
                p.setPen(QColor(11, 11, 14) if k == 0 else white)
                p.setFont(word)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, w)
        room = grid_y - 36 - y                     # place pour la carte et la suite
        # carte : l'offre, ou un message
        card_top = y
        p.save()
        p.setClipRect(QRectF(x0, card_top, PANEL_W, max(room, 0)))
        cx, cw = x + 18, inner - 36
        cy = card_top + 18
        o, m = pn.get("offer"), pn.get("msg")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(surf)
        # hauteur d'abord mesurée en dessinant sur une couche : plus simple de dessiner le fond après coup
        layer_start = cy
        texts = []
        if o:
            texts.append(("row", o["pos"], o.get("source") or ""))
            texts.append(("wrap", big, white, o["poste"], 60))
            texts.append(("wrap", msgf, light, o["entreprise"], 44))
            if o.get("chips"):
                texts.append(("chips", o["chips"]))
            texts.append(("note", o["note"], o["frac"]))
            for sign, t in (("+ ", o.get("plus")), ("- ", o.get("minus"))):
                if t:
                    texts.append(("wrap", small, light, sign + t, 66))
            if o.get("prep"):
                texts.append(("wrap", small, ORANGE, o["prep"], 40))
        elif m:
            texts.append(("wrap", big, white, m.get("title") or "Candidature", 60))
            for line in m.get("lines") or []:
                texts.append(("wrap", msgf, light, line, 70))
        # fond de la carte : hauteur estimée par une première passe sans dessin
        def measure(item):
            if item[0] == "row":
                return 20
            if item[0] == "wrap":
                flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
                return min(QFontMetrics(item[1]).boundingRect(QRect(0, 0, int(cw), 100000), flags, item[3]).height(),
                           item[4])
            if item[0] == "chips":
                return 26
            return 34
        card_h = 36 + sum(measure(it) for it in texts) + 10 * max(len(texts) - 1, 0)
        card_h = min(card_h, max(room, 0))
        p.drawRoundedRect(QRectF(x, card_top, inner, card_h), 14, 14)
        cy = layer_start
        for it in texts:
            if it[0] == "row":
                p.setFont(small)
                p.setPen(grey)
                p.drawText(QRectF(cx, cy, cw, 20), Qt.AlignmentFlag.AlignVCenter, it[1])
                p.drawText(QRectF(cx, cy, cw, 20), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), it[2])
                cy += 20
            elif it[0] == "wrap":
                cy += self._wrap(p, it[1], it[2], cx, cy, cw, it[3], it[4])
            elif it[0] == "chips":
                fm = QFontMetrics(small)
                px = cx
                for c in it[1]:
                    cwid = fm.horizontalAdvance(c) + 18
                    if px + cwid > cx + cw:
                        break
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(chip)
                    p.drawRoundedRect(QRectF(px, cy, cwid, 26), 13, 13)
                    p.setPen(white)
                    p.setFont(small)
                    p.drawText(QRectF(px, cy, cwid, 26), Qt.AlignmentFlag.AlignCenter, c)
                    px += cwid + 6
                cy += 26
            else:
                p.setPen(CAND)
                p.setFont(QFont("Atkinson Hyperlegible", 24, QFont.Weight.Bold))
                nw = QFontMetrics(p.font()).horizontalAdvance(it[1]) + 12
                p.drawText(QRectF(cx, cy, nw, 34), Qt.AlignmentFlag.AlignVCenter, it[1])
                bx, bw = cx + nw, cw - nw - 34
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(42, 42, 50))
                p.drawRoundedRect(QRectF(bx, cy + 14, bw, 6), 3, 3)
                p.setBrush(CAND)
                p.drawRoundedRect(QRectF(bx, cy + 14, bw * it[2], 6), 3, 3)
                p.setPen(grey)
                p.setFont(small)
                p.drawText(QRectF(bx + bw, cy, 34, 34), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), "/ 5")
                cy += 34
            cy += 10
        y = card_top + card_h + 12
        if pn.get("note"):
            y += self._wrap(p, msgf, CAND, x, y, inner, pn["note"], 48) + 10
        nxt = pn.get("next") or []
        if nxt and y + 30 < card_top + room:
            p.setPen(QColor(138, 142, 154))
            p.setFont(small)
            p.drawText(QRectF(x, y, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Ensuite")
            y += 24
            fm = QFontMetrics(small)
            for label, note in nxt:
                if y + 28 > card_top + room:
                    break
                p.setPen(grey)
                p.drawText(QRectF(x, y, inner - 40, 28), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(label, Qt.TextElideMode.ElideRight, int(inner - 40)))
                p.drawText(QRectF(x, y, inner, 28), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), note)
                y += 30
        p.restore()
        p.restore()

    def _paint_quota(self, p, lines):
        """Fiche du quota, coin haut gauche : logo Claude, session 5 h puis semaine dessous ; jamais estompée."""
        fm, fs = QFontMetrics(self.font_msg), QFontMetrics(self.font_small)
        pad, logo, gap = 12, 38, 12
        label_w = max(fs.horizontalAdvance(l) for l, _ in lines) + 8 if any(l for l, _ in lines) else 0
        w = pad + logo + gap + label_w + max(fm.horizontalAdvance(t) for _, t in lines) + pad + 6
        h = max(ISLET, 14 + 24 * len(lines))
        x, y = QUOTA_MARGIN, ISLAND_TOP + (ISLET - h) / 2   # coin haut gauche, centrée sur le bandeau
        p.save()
        p.setOpacity(1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, h), min(h / 2, 28), min(h / 2, 28))
        paint_claude_logo(p, x + pad + logo / 2, y + h / 2, logo / 2)
        ty = y + (h - 24 * len(lines)) / 2
        tx = x + pad + logo + gap
        for label, text in lines:
            if label:
                p.setFont(self.font_small)
                p.setPen(QColor(255, 255, 255, 150))
                p.drawText(QRectF(tx, ty, label_w, 24), Qt.AlignmentFlag.AlignVCenter, label)
            p.setFont(self.font_msg)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(tx + label_w, ty, w, 24), Qt.AlignmentFlag.AlignVCenter, text)
            ty += 24
        p.restore()

    def _paint_main(self, p):
        mode, msg = self.content[0], self.content[1]
        if self.help and not (self.rem and self.rem[0] == "current"):   # une alarme qui sonne passe devant
            self._paint_help(p, self.help)
            return
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
        font_msg = self.font_msg
        if msg:
            room = ISLAND_MAX_W - w - gap - pad
            font_msg = fit_font(self.font_msg, msg, room)
            fm_msg = QFontMetrics(font_msg)
            msg = fm_msg.elidedText(msg, Qt.TextElideMode.ElideRight, room)
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
            p.setFont(font_msg)
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
        k, _ = clock_anim(getattr(self, "anim_now", 0.0), self.clk_start, self.clk_end, getattr(self, "motion", True))
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
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        q_text = f"« {qa.get('question')} »" if qa.get("question") else ""
        q_rect = fm_q.boundingRect(QRect(0, 0, inner, 100000), flags, q_text) if q_text else QRect()
        room = ANSWER_MAX_H - 44 - (q_rect.height() + 8 if q_text else 0) - 40
        font_a = fit_font(self.font_answer, qa.get("answer") or "", inner, room)   # tout le texte, police ajustée
        fm_a = QFontMetrics(font_a)
        a_rect = fm_a.boundingRect(QRect(0, 0, inner, 100000), flags, qa.get("answer") or "")
        meta = f"Iris · disparaît dans {int(qa.get('left', 0))} s · « Iris, ferme » pour la retirer"
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
        p.setFont(font_a)
        p.save()
        p.setClipRect(QRectF(x + pad, y, inner, max(0, top + h - 36 - y)))   # jamais sur la ligne du bas
        p.drawText(QRectF(x + pad, y, inner, a_rect.height()), flags, qa.get("answer") or "")
        p.restore()
        p.setPen(QColor(255, 255, 255, 110))
        p.setFont(self.font_small)
        p.setFont(fit_font(self.font_small, meta, inner))
        p.drawText(QRectF(x + pad, top + h - 28, inner, 22), Qt.AlignmentFlag.AlignVCenter, meta)
        p.restore()

    def _paint_help(self, p, hv):
        """« iris aide » : en haut ce qui marche maintenant (mode en cours), puis toutes les commandes en 4 colonnes,
        une commande par ligne (mot en blanc, effet en gris). Le fond prend la hauteur du contenu."""
        fm = QFontMetrics(self.font_small)
        bold = QFont(self.font_small)
        bold.setBold(True)
        fmb = QFontMetrics(bold)
        pad, line, chip_h = 24, fm.height() + 6, fm.height() + 10
        left, top = (self.width - HELP_W) / 2, ISLAND_TOP
        inner = HELP_W - 2 * pad
        # 1. mise en place (positions), 2. dessin
        chips, x, y = [], 0.0, 38 + line + 4
        for word, what in hv["now"]["rows"]:
            w = fmb.horizontalAdvance(word) + 10 + fm.horizontalAdvance(what) + 24
            if x and x + w > inner:
                x, y = 0.0, y + chip_h + 6
            chips.append((x, y, w, word, what))
            x += w + 8
        y0 = y + chip_h + 22
        cols, gap = 4, 22
        colw = (inner - (cols - 1) * gap) / cols
        heights, cells = [0.0] * cols, []
        for theme, rows in hv["groups"]:
            c = heights.index(min(heights))
            cells.append((c, heights[c], theme, rows))
            heights[c] += line * (len(rows) + 1) + 16
        h = min(y0 + max(heights) + pad, HELP_H)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(left, top, HELP_W, h), 22, 22)
        L, T = left + pad, top + pad
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(L, T, inner, 26), Qt.AlignmentFlag.AlignVCenter, "AIDE · dis « iris » puis un mot")
        p.setPen(QColor(200, 205, 214))
        p.setFont(self.font_small)
        p.drawText(QRectF(L, T, inner, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "« ferme » ou « merci » pour fermer")
        p.setPen(BLUE)
        p.setFont(bold)
        p.drawText(QRectF(L, T + 38, inner, line), Qt.AlignmentFlag.AlignVCenter, hv["now"]["title"])
        for x, y, w, word, what in chips:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(111, 155, 245, 60))
            p.drawRoundedRect(QRectF(L + x, T + y, w, chip_h), chip_h / 2, chip_h / 2)
            p.setPen(QColor(255, 255, 255))
            p.setFont(bold)
            p.drawText(QRectF(L + x + 12, T + y, w, chip_h), Qt.AlignmentFlag.AlignVCenter, word)
            p.setPen(QColor(200, 205, 214))
            p.setFont(self.font_small)
            p.drawText(QRectF(L + x + 22 + fmb.horizontalAdvance(word), T + y, w, chip_h),
                       Qt.AlignmentFlag.AlignVCenter, what)
        for c, dy, theme, rows in cells:
            cx, cy = L + c * (colw + gap), T + y0 + dy
            p.setPen(ORANGE)
            p.setFont(bold)
            p.drawText(QRectF(cx, cy, colw, line), Qt.AlignmentFlag.AlignVCenter, theme.upper())
            for word, what in rows:
                cy += line
                ww = fmb.horizontalAdvance(word)
                p.setPen(QColor(255, 255, 255))
                p.setFont(bold)
                p.drawText(QRectF(cx, cy, colw, line), Qt.AlignmentFlag.AlignVCenter, word)
                p.setPen(QColor(170, 176, 188))
                p.setFont(self.font_small)
                room = int(colw - ww - 10)
                p.drawText(QRectF(cx + ww + 10, cy, room, line), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(what, Qt.TextElideMode.ElideRight, room))
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
        font_body = fit_font(self.font_rem if kind == "current" else self.font_answer, body, inner,
                             ANSWER_MAX_H - 46 - 44)       # tout le texte : la police rapetisse s'il le faut
        font_title = fit_font(self.font_mode, title, inner - ICON - 10)
        font_meta = fit_font(self.font_small, meta, inner)
        alarm = kind == "current" and data.get("alarm")
        ringing = kind == "current" and data.get("ringing")
        fm_b, fm_s = QFontMetrics(font_body), QFontMetrics(font_meta)
        b_rect = fm_b.boundingRect(QRect(0, 0, inner, 100000), flags, body)
        h = min(ANSWER_MAX_H, 46 + b_rect.height() + 44)
        if ringing:      # pulsation : 1 s, entre rouge sombre et rouge vif (rouge vif fixe sans animation)
            k = 0.5 + 0.5 * math.sin(_t.monotonic() * 2 * math.pi) if getattr(self, "motion", True) else 1.0
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
        p.setFont(font_title)
        p.drawText(QRectF(x + pad + ICON + 10, top, inner - ICON - 10, 46), Qt.AlignmentFlag.AlignVCenter, title)
        p.setFont(font_body)
        p.save()
        p.setClipRect(QRectF(x + pad, top + 46, inner, max(0, h - 46 - 36)))
        p.drawText(QRectF(x + pad, top + 46, inner, b_rect.height()), flags, body)
        p.restore()
        p.setPen(QColor(255, 255, 255, 170))
        p.setFont(font_meta)
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
        k, angle = clock_anim(getattr(self, "anim_now", 0.0), self.clk_start, self.clk_end, getattr(self, "motion", True))
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
        paint_logo(p, x, y, ISLET, self.logos.get(self.logo), self.ring)
