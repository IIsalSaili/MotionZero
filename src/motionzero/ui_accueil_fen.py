"""Page d'accueil, maquette B « menu latéral » (plan-accueil.md, étape 3) : Maintenant, Réglages, Consommation."""
import ctypes

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout,
                               QWidget)

from .accueil import HOME_TITLE, conso_line
from .reglages import SECTIONS, read_section, write_section
from .ui_accueil_conso import ConsoPage
from .ui_accueil_pages import _FONT, HOME, RailButton, SettingsPage
from .ui_ile import HomeLogo, load_fonts

MODE_COLORS_HOME = {"CHROME": HOME["chrome"], "NEUTRE": HOME["off"], "PAUSE": HOME["off"]}
TONE_COLORS = {"listen": HOME["ok"], "busy": HOME["lecture"], "off": HOME["off"], "idle": HOME["texte"]}
SENSOR_COLORS = {"ok": HOME["ok"], "off": HOME["souris"], "idle": HOME["off"], "fail": HOME["erreur"]}
SECTION_NAMES = {"maintenant": "Maintenant", "reglages": "Réglages", "conso": "Conso"}


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _card_title(text):
    return (f"<div style='color:{HOME['off']};font-size:11pt;font-weight:bold;letter-spacing:2px'>"
            f"{_esc(text.upper())}</div>")


def now_html(title, rows):
    """Carte « Ici, maintenant » : effet à gauche, mot à dire en vert. Pur : testable."""
    lines = "".join(
        f"<tr><td style='padding:3px 12px 3px 0'>{_esc(what)}</td>"
        f"<td style='padding:3px 0;color:{HOME['ok']};font-weight:bold' align='right'>{_esc(word)}</td></tr>"
        for word, what in rows)
    return _card_title(title) + f"<table width='100%' style='font-size:13pt'>{lines}</table>"


def sensors_html(items):
    """Carte des capteurs et services, une ligne chacun. Pur : testable."""
    out = []
    for name, state, detail in items:
        c = SENSOR_COLORS.get(state, HOME["off"])
        d = f" <span style='color:{HOME['texte2']}'>{_esc(detail)}</span>" if detail else ""
        out.append(f"<span style='color:{c}'>●</span>&nbsp; {_esc(name)}{d}")
    return _card_title("Capteurs") + "<div style='font-size:13pt'>" + "<br>".join(out) + "</div>"


def last_html(items):
    """Dernières commandes : vert compris, rouge refusé, avec leur âge. Pur : testable."""
    if not items:
        return _card_title("Dernières commandes") + f"<span style='color:{HOME['off']}'>Aucune commande récente</span>"
    rows = []
    for label, ok, age in items:
        c, sign = (HOME["ok"], "✓") if ok else (HOME["erreur"], "✗")
        rows.append(f"<tr><td style='color:{c};padding:2px 12px 2px 0'>{sign} {_esc(label)}</td>"
                    f"<td align='right' style='color:{HOME['texte2']}'>il y a {age:.0f} s</td></tr>")
    return _card_title("Dernières commandes") + f"<table width='100%' style='font-size:13pt'>{''.join(rows)}</table>"


def _card():
    lbl = QLabel()
    lbl.setWordWrap(True)
    lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(f"background: {HOME['surface']}; border: 1px solid {HOME['bord']}; border-radius: 16px;"
                      f" padding: 14px 18px;")
    return lbl


def _chip(color):
    return (f"background: {color}; color: {HOME['fond']}; border-radius: 14px; padding: 4px 14px;"
            f" font: bold 12pt {_FONT}; letter-spacing: 2px;")


class PreviewWindow(QWidget):
    closed = Signal()
    reglage_clicked = Signal(str)              # id du registre : traité par la boucle principale (jamais ici)
    quit_clicked = Signal()                    # « fermer Iris » : arrêt voulu, sans relance

    def __init__(self, pointer="main", quiet="auto", volume=0.5, lecture=False, section_file=None):
        super().__init__()
        load_fonts()
        self.setWindowTitle(HOME_TITLE)
        self.setStyleSheet(f"PreviewWindow {{ background: {HOME['fond']}; }}"
                           f"QLabel {{ color: {HOME['texte']}; font-family: {_FONT}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._section_file = section_file

        # menu étroit de gauche
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setStyleSheet("#rail { background: #000; }")
        rail.setFixedWidth(112)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(12, 16, 12, 16)
        rl.setSpacing(8)
        self.logo = HomeLogo()
        rl.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        rl.addSpacing(10)
        self.nav = {}
        for name in SECTIONS:
            b = RailButton(SECTION_NAMES[name], name)
            b.clicked.connect(lambda _=False, n=name: self.show_section(n))
            self.nav[name] = b
            rl.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        rl.addStretch(1)
        self.quit_btn = RailButton("Fermer", "fermer", danger=True)
        self.quit_btn.setToolTip("Ferme Iris pour de bon : le gardien ne la relance pas")
        self.quit_btn.clicked.connect(self.quit_clicked.emit)
        rl.addWidget(self.quit_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # bandeau du haut, commun aux sections : état, mode, souris, mots d'aide
        bar = QWidget()
        bar.setObjectName("bar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setStyleSheet("#bar { background: #000; border-radius: 34px; }")
        bar.setFixedHeight(68)
        self.state_lbl = QLabel("Démarrage…")
        self.state_lbl.setStyleSheet(f"font: bold 22pt {_FONT};")
        self.mode_lbl = QLabel()
        self.mouse_lbl = QLabel("SOURIS")
        self.mouse_lbl.setStyleSheet(_chip(HOME["souris"]))
        self.mouse_lbl.hide()
        hint = QLabel(f"Toutes les commandes : <b style='color:{HOME['ok']}'>iris aide</b>"
                      f" &nbsp;·&nbsp; doc : <b style='color:{HOME['ok']}'>iris guide</b>")
        hint.setStyleSheet(f"color: {HOME['texte2']}; font-size: 12pt;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 0, 24, 0)
        bl.setSpacing(16)
        for w in (self.state_lbl, self.mode_lbl, self.mouse_lbl):
            bl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        bl.addStretch(1)
        bl.addWidget(hint)

        # section Maintenant : caméra et dernières commandes à gauche ; mots, capteurs, conso à droite
        now = QWidget()
        g = QGridLayout(now)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(16)
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setText("Démarrage de la caméra…")
        self.label.setMinimumSize(420, 300)
        # l'image suit la taille de la zone, jamais l'inverse (sinon la fenêtre grandit à chaque image)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.label.setStyleSheet(f"background: #060608; border: 1px solid {HOME['bord']}; border-radius: 16px;"
                                 f" color: {HOME['texte2']}; font-size: 14pt;")
        self.last_lbl, self.now_lbl, self.sensors_lbl, self.conso_lbl = _card(), _card(), _card(), _card()
        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self.label, 1)
        left.addWidget(self.last_lbl)
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self.now_lbl, 1)
        right.addWidget(self.sensors_lbl)
        right.addWidget(self.conso_lbl)
        g.addLayout(left, 0, 0)
        g.addLayout(right, 0, 1)
        g.setColumnStretch(0, 13)
        g.setColumnStretch(1, 10)

        self.settings = SettingsPage()
        self.settings.clicked.connect(self.reglage_clicked.emit)
        self.conso = ConsoPage()
        self.stack = QStackedWidget()
        self.pages = {"maintenant": now, "reglages": self.settings, "conso": self.conso}
        for name in SECTIONS:
            self.stack.addWidget(self.pages[name])

        main = QVBoxLayout()
        main.setContentsMargins(24, 20, 24, 20)
        main.setSpacing(16)
        main.addWidget(bar)
        main.addWidget(self.stack, 1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(rail)
        lay.addLayout(main, 1)

        self._home = None
        self.pointer = pointer
        for rid, value in (("souris", pointer), ("camera", False), ("conversation", True), ("voix_basse", quiet),
                           ("volume", volume), ("lecture", lecture), ("son", False)):
            self.set_reglage(rid, value)
        self.set_stats(None)
        self.set_home({"state": "Démarrage…", "tone": "idle", "mode": "NEUTRE", "mouse": False,
                       "now_title": "Maintenant", "now_rows": [], "sensors": [], "last": []})
        self.section = None
        self.show_section(read_section(section_file) if section_file else SECTIONS[0], save=False)
        self.resize(1280, 760)
        self.visible_flag = True   # lu par le moteur : réduite, l'aperçu n'est plus dessiné

    def show_section(self, name, save=True):
        if name not in self.pages or name == self.section:
            return
        self.section = name
        self.stack.setCurrentWidget(self.pages[name])
        for n, b in self.nav.items():
            b.set_on(n == name)
        if save and self._section_file:
            write_section(name, self._section_file)   # simple fichier, rien de Core : sans risque dans le fil Qt

    def set_reglage(self, rid, value):
        """Valeur courante d'un réglage (venue de la boucle principale par le pont)."""
        if rid == "souris":
            self.pointer = value
        self.settings.set_value(rid, value)

    # appelées par le pont (bridge.* -> fil Qt)
    def set_pointer(self, pointer):
        self.set_reglage("souris", pointer)

    def set_volume(self, volume):
        self.set_reglage("volume", volume)

    def set_conversation(self, on):
        self.set_reglage("conversation", on)

    def set_camera(self, off):
        self.set_reglage("camera", off)

    def set_quiet(self, choice):
        self.set_reglage("voix_basse", choice)

    def set_lecture(self, on):
        self.set_reglage("lecture", on)

    def set_repair_busy(self, busy):
        self.set_reglage("son", busy)

    def set_stats(self, s):
        self.conso_lbl.setText(_card_title("Consommation") + f"<div style='font-size:13pt'>{_esc(conso_line(s))}</div>")
        self.conso.set_stats(s)

    def set_home(self, v):
        """Contenu calculé par accueil.home_view ; on ne redessine que ce qui a changé."""
        if v == self._home:
            return
        old, self._home = self._home or {}, v
        if (v.get("state"), v.get("tone")) != (old.get("state"), old.get("tone")):
            self.state_lbl.setText(v.get("state", ""))
            self.state_lbl.setStyleSheet(f"font: bold 22pt {_FONT}; color: {TONE_COLORS.get(v.get('tone'), HOME['texte'])};")
        if v.get("mode") != old.get("mode"):
            m = v.get("mode", "")
            self.mode_lbl.setText(m)
            self.mode_lbl.setStyleSheet(_chip(MODE_COLORS_HOME.get(m, HOME["off"])))
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
        if self.section != "maintenant":
            return                            # image cachée : rien à dessiner
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
