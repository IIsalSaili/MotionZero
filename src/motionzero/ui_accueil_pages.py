"""Pièces de la page d'accueil, maquette B (plan-accueil.md, étapes 2 et 4) : menu, cartes, consommation."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .reglages import par_groupe, tile_text

HOME = {"fond": "#0B0B0E", "surface": "#17171C", "bord": "#2A2A32", "texte": "#F2F2F5", "texte2": "#A6A6B0",
        "off": "#6E6E78", "lecture": "#B48CFF", "souris": "#F5A524", "chrome": "#6F9BF5", "ok": "#34C759",
        "erreur": "#FF5A5F"}
_FONT = "'Atkinson Hyperlegible'"
TONES = {"ok": HOME["ok"], "alerte": HOME["souris"], "neutre": HOME["texte"]}
TILE_W, TILE_H = 260, 118
_KEEP = {}                      # widgets décoratifs gardés en vie


def _no_focus(b):
    # jamais au clavier : une touche Espace envoyée par Iris ou la dictée « cliquait » le bouton
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def fits(text, px, width, bold=True):
    """Le texte tient-il dans la largeur, en Atkinson Hyperlegible gras ? (test : aucun débordement)"""
    f = QFont("Atkinson Hyperlegible")
    f.setPixelSize(px)
    f.setBold(bold)
    return QFontMetrics(f).horizontalAdvance(text) <= width


class RailButton(QPushButton):
    """Bouton du menu étroit de gauche : icône dessinée au-dessus du nom."""
    def __init__(self, name, icon, danger=False):
        super().__init__()
        self.name, self.icon, self.danger, self.on = name, icon, danger, False
        self.setFixedSize(88, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        _no_focus(self)

    def set_on(self, on):
        self.on = on
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.on:
            p.setPen(QPen(QColor(HOME["bord"]), 1))
            p.setBrush(QColor(HOME["surface"]))
            p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 16, 16)
        c = QColor("#FF8A8E" if self.danger else (HOME["texte"] if self.on or self.underMouse() else HOME["texte2"]))
        pen = QPen(c, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = self.width() / 2, 28
        if self.icon == "maintenant":
            p.drawEllipse(QPointF(cx, cy), 11, 11)
            p.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx + 4, cy + 3))
        elif self.icon == "reglages":
            for i, k in enumerate((0.7, 0.3, 0.55)):
                y = cy - 8 + i * 8
                p.drawLine(QPointF(cx - 12, y), QPointF(cx + 12, y))
                p.setBrush(QColor(HOME["fond"]))
                p.drawEllipse(QPointF(cx - 12 + 24 * k, y), 2.6, 2.6)
                p.setBrush(Qt.BrushStyle.NoBrush)
        elif self.icon == "conso":
            p.drawLine(QPointF(cx - 12, cy + 10), QPointF(cx + 12, cy + 10))
            p.drawPolyline(QPolygonF([QPointF(cx - 9, cy + 5), QPointF(cx - 3, cy - 2), QPointF(cx + 2, cy + 2),
                                      QPointF(cx + 9, cy - 9)]))
        elif self.icon == "fermer":
            p.drawLine(QPointF(cx, cy - 11), QPointF(cx, cy - 1))
            p.drawArc(QRectF(cx - 10, cy - 8, 20, 20), 120 * 16, 300 * 16)
        p.setPen(c)
        f = QFont("Atkinson Hyperlegible")
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 48, self.width(), 24), Qt.AlignmentFlag.AlignCenter, self.name)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()


class Tile(QPushButton):
    """Carte d'un réglage : titre en petites capitales, valeur en grand, note dessous. Clic = choix suivant."""
    def __init__(self, reglage):
        super().__init__()
        self.reglage = reglage
        self.setMinimumSize(TILE_W, TILE_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        _no_focus(self)
        bg, bd = ("#2A0D10", "#5A2027") if reglage.danger else (HOME["surface"], HOME["bord"])
        self.setStyleSheet(f"Tile {{ background: {bg}; border: 1px solid {bd}; border-radius: 18px; }}"
                           f"Tile:hover {{ border: 2px solid {HOME['texte2']}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        self.k = QLabel(reglage.titre.upper())
        self.v = QLabel()
        self.n = QLabel()
        self.k.setStyleSheet(f"color: {HOME['texte2']}; font: bold 11pt {_FONT}; letter-spacing: 1px; background: transparent;")
        self.n.setStyleSheet(f"color: {HOME['off']}; font: 11pt {_FONT}; background: transparent;")
        for w in (self.k, self.v, self.n):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lay.addWidget(w)
        lay.insertStretch(2, 1)
        self.value = None

    def set_value(self, value):
        self.value = value
        text, note, tone = tile_text(self.reglage.id, value)
        self.v.setText(text)
        self.v.setStyleSheet(f"color: {TONES.get(tone, HOME['texte'])}; font: bold 18pt {_FONT}; background: transparent;")
        self.n.setText(note)


class SettingsPage(QWidget):
    """Section « Réglages » : une grille de cartes par groupe, tirée du registre."""
    clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.tiles = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        head = QLabel(f"<span style='font-size:22pt;font-weight:bold'>Réglages</span>"
                      f"&nbsp;&nbsp;<span style='color:{HOME['texte2']};font-size:12pt'>"
                      f"un clic sur une carte passe au choix suivant</span>")
        lay.addWidget(head)
        for groupe, regs in par_groupe():
            g = QLabel(groupe.upper())
            g.setStyleSheet(f"color: {HOME['off']}; font: bold 11pt {_FONT}; letter-spacing: 2px;")
            lay.addWidget(g)
            grid = QGridLayout()
            grid.setSpacing(14)
            for i, r in enumerate(regs):
                t = Tile(r)
                t.clicked.connect(lambda _=False, rid=r.id: self.clicked.emit(rid))
                self.tiles[r.id] = t
                grid.addWidget(t, i // 3, i % 3)
            for i in range(len(regs), -(-len(regs) // 3) * 3):   # cases vides : même largeur partout
                grid.addWidget(QWidget(), i // 3, i % 3)
            for c in range(3):
                grid.setColumnStretch(c, 1)
            lay.addLayout(grid)
        lay.addStretch(1)

    def set_value(self, rid, value):
        if rid in self.tiles:
            self.tiles[rid].set_value(value)


class Curve(QWidget):
    """Courbe sur 2 min (historique de stats.py), 0-100 %. Dessinée seulement quand elle change."""
    def __init__(self, color):
        super().__init__()
        self.color, self.points = color, []
        self.setMinimumHeight(140)

    def set_points(self, pts):
        pts = [float(x) for x in (pts or []) if x is not None]
        if pts != self.points:
            self.points = pts
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(HOME["bord"]), 1))
        for k in (0, 0.5, 1):
            p.drawLine(QPointF(0, 4 + (h - 8) * k), QPointF(w, 4 + (h - 8) * k))
        if len(self.points) < 2:
            return
        n = len(self.points)
        poly = QPolygonF([QPointF(w * i / (n - 1), 4 + (h - 8) * (1 - min(max(v, 0), 100) / 100))
                          for i, v in enumerate(self.points)])
        p.setPen(QPen(QColor(self.color), 2.5))
        p.drawPolyline(poly)


def _dec(x):
    return f"{x:.1f}".replace(".", ",")


def conso_details(s):
    """Lignes de la section Consommation (texte riche). Pur : testable ; mesure absente = message."""
    if not s:
        return ["Mesure en cours…"]
    out = [f"Processeur : Iris {s.get('app_cpu', 0):.0f} %"
           + (f" · PC {s['pc_cpu']:.0f} %" if s.get("pc_cpu") is not None else "")]
    ram = f"Mémoire : Iris {_dec(s.get('app_private', 0) / 1024)} Go"
    if s.get("pc_ram_total"):
        ram += f" · PC {_dec(s.get('pc_ram_used', 0))} / {s['pc_ram_total']:.0f} Go"
    out.append(ram)
    if s.get("app_gpu") is not None or s.get("pc_gpu") is not None:
        g = "Carte graphique :"
        if s.get("app_gpu") is not None:
            g += f" Iris {s['app_gpu']:.0f} %"
        if s.get("pc_gpu") is not None:
            g += f" · PC {s['pc_gpu']:.0f} %"
        if s.get("app_vram") is not None:
            g += f" · {s['app_vram']:.0f} Mo"
        out.append(g)
    models = [("Whisper chargé" if s.get("whisper") else "Whisper au repos")]
    if s.get("detect_hz") is not None:
        models.append(f"gestes {s['detect_hz']:.0f} images/s")
    if s.get("voice_on") is False:
        models.append("voix coupée")
    out.append("Modèles : " + " · ".join(models))
    th = s.get("threads") or []
    if isinstance(th, dict):
        th = sorted(th.items(), key=lambda kv: -kv[1])
    busy = []
    for item in list(th)[:3]:
        try:
            name, pct = item[0], float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        busy.append(f"{name} {pct:.0f} %")
    if busy:
        out.append("Fils les plus occupés : " + " · ".join(busy))
    return out


class ConsoPage(QWidget):
    """Section « Consommation » : courbes Iris / PC et détails. Mesurée seulement quand visible (run_sampler)."""
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(QLabel("<span style='font-size:22pt;font-weight:bold'>Consommation</span>"))
        leg = QLabel(f"<span style='color:{HOME['ok']}'>━ Iris</span>&nbsp;&nbsp;&nbsp;"
                     f"<span style='color:{HOME['chrome']}'>━ PC entier</span>"
                     f"&nbsp;&nbsp;&nbsp;<span style='color:{HOME['texte2']}'>processeur, 2 dernières minutes</span>")
        leg.setStyleSheet("font-size: 12pt;")
        lay.addWidget(leg)
        box = QWidget()
        box.setObjectName("courbes")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setStyleSheet(f"#courbes {{ background: {HOME['surface']}; border: 1px solid {HOME['bord']};"
                          f" border-radius: 16px; }}")
        bl = QGridLayout(box)
        bl.setContentsMargins(16, 16, 16, 16)
        self.app_curve, self.pc_curve = Curve(HOME["ok"]), Curve(HOME["chrome"])
        bl.addWidget(self.pc_curve, 0, 0)
        bl.addWidget(self.app_curve, 0, 0)       # superposées : Iris par-dessus
        self.app_curve.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay.addWidget(box, 1)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setStyleSheet("font-size: 14pt; line-height: 150%;")
        lay.addWidget(self.details)
        self.set_stats(None)

    def set_stats(self, s):
        self.details.setText("<br>".join(conso_details(s)))
        hist = (s or {}).get("history") or {}
        self.app_curve.set_points(hist.get("app_cpu"))
        self.pc_curve.set_points(hist.get("pc_cpu"))
