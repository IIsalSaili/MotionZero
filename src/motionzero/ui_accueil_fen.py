"""Fenêtre d'aperçu caméra et page d'accueil (découpé de ui.py, #52)."""
import ctypes

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .accueil import HOME_TITLE, conso_line
from .ui_ile import HomeLogo, load_fonts


def pointer_button_text(pointer):
    """Texte du bouton de l'accueil. Pur : testable."""
    return "Souris : tête  ·  passer à la main" if pointer == "tete" else "Souris : main  ·  passer à la tête"


def quiet_button_text(choice):
    """Texte du bouton « voix basse » de l'accueil. Pur : testable."""
    return {"oui": "Voix basse : toujours", "non": "Voix basse : jamais"}.get(
        choice, "Voix basse : le soir (22 h - 7 h)")


def conversation_button_text(on):
    """Texte du bouton « mode conversation » de l'accueil. Pur : testable."""
    return ("[x] Mode conversation : mot noyé dans une phrase ignoré" if on
            else "[  ] Mode conversation : chaque mot reconnu compte")


def camera_button_text(off):
    """Texte du bouton « caméra » de l'accueil. Pur : testable."""
    return "Caméra coupée  ·  la rallumer" if off else "Caméra allumée  ·  la couper"


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
    camera_clicked = Signal()                  # « caméra » : idem
    conversation_clicked = Signal()            # « mode conversation » : idem
    quit_clicked = Signal()                    # « fermer Iris » : arrêt voulu, sans relance

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
        self.conv_btn = QPushButton(conversation_button_text(True))
        self.conv_btn.setToolTip("Coché : un mot dit au milieu d'une conversation est ignoré. Décoché : tout mot reconnu agit")
        self.quit_btn = QPushButton("Fermer Iris")
        self.quit_btn.setToolTip("Ferme Iris pour de bon : le gardien ne la relance pas")
        self.camera_btn = QPushButton(camera_button_text(False))
        self.camera_btn.setToolTip("Rend la webcam aux autres applis (appel Discord). Gestes en pause tant qu'elle est coupée")
        for b in (self.main_btn, self.head_btn, self.quiet_btn, self.volume_btn, self.camera_btn, self.conv_btn,
                  self.quit_btn):
            b.setMinimumHeight(64)             # grande cible (clic à la main ou à la tête)
            # jamais au clavier : avec le focus, une touche Espace (envoyée par Iris, la dictée, un réveil…)
            # « cliquait » le bouton sans que personne ne l'ait touché
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for b in (self.quiet_btn, self.volume_btn, self.camera_btn, self.conv_btn):
            b.setStyleSheet(_pill_style("#000", HOME["texte"], "#555"))
        self.quit_btn.setStyleSheet(_pill_style("#3A0E12", "#FFD6D9", "#7A2A30"))
        self.main_btn.clicked.connect(lambda: self._choose_pointer("main"))
        self.head_btn.clicked.connect(lambda: self._choose_pointer("tete"))
        self.quiet_btn.clicked.connect(self.quiet_clicked.emit)
        self.volume_btn.clicked.connect(self.volume_clicked.emit)
        self.camera_btn.clicked.connect(self.camera_clicked.emit)
        self.conv_btn.clicked.connect(self.conversation_clicked.emit)
        self.quit_btn.clicked.connect(self.quit_clicked.emit)
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
        right.addWidget(self.camera_btn)
        right.addWidget(self.conv_btn)
        right.addWidget(self.quit_btn)

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

    def set_conversation(self, on):
        self.conv_btn.setText(conversation_button_text(on))

    def set_camera(self, off):
        self.camera_btn.setText(camera_button_text(off))

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
