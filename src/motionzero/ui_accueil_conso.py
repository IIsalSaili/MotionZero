"""Section « Consommation » de l'accueil : des graphes, un chiffre clé par carte (plan-accueil.md, étape 4)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from .ui_accueil_pages import _FONT, HOME

IRIS, PC = HOME["ok"], HOME["chrome"]


def _dec(x):
    return f"{x:.1f}".replace(".", ",")


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def conso_view(s):
    """Tout ce que les graphes dessinent, en un dict. Pur : testable ; mesure absente ou partielle = valeurs vides."""
    s = s or {}
    h = s.get("history") or {}
    pts = lambda k: [x for x in (_num(v) for v in (h.get(k) or [])) if x is not None]
    app_mo, pc_used, pc_tot = _num(s.get("app_private")), _num(s.get("pc_ram_used")), _num(s.get("pc_ram_total"))
    vram_used, vram_tot, app_vram = _num(s.get("pc_vram_used")), _num(s.get("pc_vram_total")), _num(s.get("app_vram"))
    threads = []
    for item in list(s.get("threads") or [])[:5]:
        try:
            threads.append((str(item[0]), float(item[1])))
        except (TypeError, ValueError, IndexError):
            continue
    cores = [x for x in (_num(c) for c in (s.get("cores") or [])) if x is not None]
    gpu_on = s.get("app_gpu") is not None or s.get("pc_gpu") is not None
    return {
        "measured": bool(s),
        "cpu": {"iris": pts("app_cpu"), "pc": pts("pc_cpu"), "now": _num(s.get("app_cpu")), "pc_now": _num(s.get("pc_cpu"))},
        "gpu": {"iris": pts("app_gpu"), "pc": pts("pc_gpu"), "now": _num(s.get("app_gpu")), "pc_now": _num(s.get("pc_gpu")),
                "on": gpu_on, "name": s.get("gpu_name") or ""},
        "ram": {"iris_go": None if app_mo is None else app_mo / 1024, "used": pc_used, "total": pc_tot,
                "trend": [x / 1024 for x in pts("app_private")]},
        "vram": {"used": vram_used, "total": vram_tot, "iris": app_vram},
        "cores": cores,
        "threads": threads,
        "models": [("Whisper", "chargé" if s.get("whisper") else "au repos", bool(s.get("whisper"))),
                   ("Gestes", f"{s['detect_hz']:.0f} images/s" if _num(s.get("detect_hz")) is not None else "?",
                    bool(_num(s.get("detect_hz")))),
                   ("Voix", "coupée" if s.get("voice_on") is False else "active", s.get("voice_on") is not False)],
    }


def _font(px, bold=False):
    f = QFont("Atkinson Hyperlegible")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class Chart(QWidget):
    """Une zone de dessin ; le contenu (dict de conso_view) est donné par set_data."""
    kind = ""

    def __init__(self):
        super().__init__()
        self.data = None
        self.setMinimumHeight(90)

    def set_data(self, data):
        if data != self.data:
            self.data = data
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self.draw(p, self.width(), self.height(), self.data)
        finally:
            p.end()

    def empty(self, p, w, h, text="mesure en cours…"):
        p.setPen(QColor(HOME["off"]))
        p.setFont(_font(14))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)


class Lines(Chart):
    """Courbes Iris / PC, 0-100 %, sur la dernière minute."""
    def draw(self, p, w, h, d):
        if not d or (len(d.get("iris", [])) < 2 and len(d.get("pc", [])) < 2):
            return self.empty(p, w, h, d.get("absent", "mesure en cours…") if d else "mesure en cours…")
        p.setPen(QPen(QColor(HOME["bord"]), 1))
        for k in (0, 0.5, 1):
            p.drawLine(QPointF(0, 4 + (h - 8) * k), QPointF(w, 4 + (h - 8) * k))
        for key, color in (("pc", PC), ("iris", IRIS)):
            v = d.get(key) or []
            if len(v) < 2:
                continue
            n = len(v)
            poly = QPolygonF([QPointF(w * i / (n - 1), 4 + (h - 8) * (1 - min(max(x, 0), 100) / 100))
                              for i, x in enumerate(v)])
            p.setPen(QPen(QColor(color), 2.5))
            p.drawPolyline(poly)


class Gauges(Chart):
    """Barres horizontales « utilisé / total », avec la part d'Iris en vert par-dessus."""
    def draw(self, p, w, h, rows):
        rows = [r for r in (rows or []) if r[2]]
        if not rows:
            return self.empty(p, w, h, "indisponible")
        bh, gap = 26, 34
        top = max(24, (h - len(rows) * (bh + gap) + gap) / 2 + 10)
        for i, (label, used, total, iris, text) in enumerate(rows):
            y = top + i * (bh + gap)
            p.setPen(QColor(HOME["texte2"]))
            p.setFont(_font(13, True))
            p.drawText(QRectF(0, y - 22, w, 20), Qt.AlignmentFlag.AlignLeft, label)
            p.drawText(QRectF(0, y - 22, w, 20), Qt.AlignmentFlag.AlignRight, text)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(HOME["bord"]))
            p.drawRoundedRect(QRectF(0, y, w, bh), 8, 8)
            p.setBrush(QColor(PC))
            p.drawRoundedRect(QRectF(0, y, w * min((used or 0) / total, 1), bh), 8, 8)
            if iris:
                p.setBrush(QColor(IRIS))
                p.drawRoundedRect(QRectF(0, y, max(w * min(iris / total, 1), 4), bh), 8, 8)


class Columns(Chart):
    """Une colonne par cœur du processeur, 0-100 %."""
    def draw(self, p, w, h, cores):
        if not cores:
            return self.empty(p, w, h)
        n = len(cores)
        gap = 4 if n > 16 else 6
        cw = (w - gap * (n - 1)) / n
        p.setPen(Qt.PenStyle.NoPen)
        for i, c in enumerate(cores):
            x = i * (cw + gap)
            p.setBrush(QColor(HOME["bord"]))
            p.drawRoundedRect(QRectF(x, 0, cw, h), 4, 4)
            ch = h * min(max(c, 0), 100) / 100
            p.setBrush(QColor(HOME["erreur"] if c > 85 else (HOME["souris"] if c > 60 else PC)))
            p.drawRoundedRect(QRectF(x, h - ch, cw, ch), 4, 4)


class Ranking(Chart):
    """Fils les plus occupés : barres horizontales, nom et % d'un cœur."""
    def draw(self, p, w, h, rows):
        if not rows:
            return self.empty(p, w, h)
        top_v = max(max(v for _, v in rows), 1)
        lab = min(190, w * 0.45)
        bh = min(28, (h - 6 * (len(rows) - 1)) / len(rows))
        p.setFont(_font(13, True))
        for i, (name, v) in enumerate(rows):
            y = i * (bh + 6)
            p.setPen(QColor(HOME["texte"]))
            p.drawText(QRectF(0, y, lab - 10, bh), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(lab - 10)))
            bw = (w - lab - 56) * v / top_v
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(IRIS))
            p.drawRoundedRect(QRectF(lab, y + 4, max(bw, 3), bh - 8), 6, 6)
            p.setPen(QColor(HOME["texte2"]))
            p.drawText(QRectF(lab + bw + 8, y, 56, bh), Qt.AlignmentFlag.AlignVCenter, f"{v:.0f} %")


class Card(QWidget):
    """Carte : titre, chiffre clé à droite, graphe dessous."""
    def __init__(self, title, chart, legend=False):
        super().__init__()
        self.setObjectName("carte")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#carte {{ background: {HOME['surface']}; border: 1px solid {HOME['bord']};"
                           f" border-radius: 16px; }}")
        self.chart = chart
        lay = QGridLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setVerticalSpacing(10)
        t = QLabel(title.upper())
        t.setStyleSheet(f"color: {HOME['off']}; font: bold 11pt {_FONT}; letter-spacing: 2px;")
        self.value = QLabel()
        self.value.setStyleSheet(f"font: bold 20pt {_FONT};")
        lay.addWidget(t, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.value, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if legend:
            leg = QLabel(f"<span style='color:{IRIS}'>━ Iris</span>&nbsp;&nbsp;<span style='color:{PC}'>━ PC</span>"
                         f"&nbsp;&nbsp;<span style='color:{HOME['off']}'>dernière minute</span>")
            leg.setStyleSheet("font-size: 11pt;")
            lay.addWidget(leg, 1, 0, 1, 2)
        lay.addWidget(chart, 2, 0, 1, 2)
        lay.setRowStretch(2, 1)

    def set(self, value, data):
        self.value.setText(value)
        self.chart.set_data(data)


def _pct(v):
    return "–" if v is None else f"{v:.0f} %"


class ConsoPage(QWidget):
    """Six cartes : processeur, carte graphique, mémoire, cœurs, fils, modèles. Mesurées seulement si visibles."""
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.models = QLabel()
        self.models.setStyleSheet("font-size: 13pt;")
        head = QGridLayout()
        head.addWidget(QLabel("<span style='font-size:22pt;font-weight:bold'>Consommation</span>"), 0, 0)
        legend = QLabel(f"<span style='color:{IRIS}'>■</span> Iris&nbsp;&nbsp;&nbsp;"
                        f"<span style='color:{PC}'>■</span> PC entier&nbsp;&nbsp;&nbsp;"
                        f"<span style='color:{HOME['texte2']}'>courbes : dernière minute</span>")
        legend.setStyleSheet("font-size: 13pt;")
        head.addWidget(legend, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        head.setColumnStretch(2, 1)
        head.addWidget(self.models, 0, 3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)
        self.cpu = Card("Processeur", Lines())
        self.gpu = Card("Carte graphique", Lines())
        self.mem = Card("Mémoire", Gauges())
        self.cores = Card("Cœurs du processeur", Columns())
        self.threads = Card("Fils les plus occupés", Ranking())
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.addWidget(self.cpu, 0, 0)
        grid.addWidget(self.gpu, 0, 1)
        grid.addWidget(self.mem, 1, 0)
        grid.addWidget(self.cores, 1, 1)
        grid.addWidget(self.threads, 2, 0, 1, 2)
        for i in range(2):
            grid.setColumnStretch(i, 1)
        for r in range(3):
            grid.setRowStretch(r, 1)
        lay.addLayout(grid, 1)
        self.set_stats(None)

    def set_stats(self, s):
        v = conso_view(s)
        self.cpu.set(_pct(v["cpu"]["now"]), v["cpu"])
        g = dict(v["gpu"], absent="mesure en cours…" if not v["measured"] else "carte graphique illisible")
        self.gpu.set(_pct(g["now"] if g["now"] is not None else g["pc_now"]), g)
        r, vr = v["ram"], v["vram"]
        rows = [("Mémoire vive", r["used"], r["total"], r["iris_go"],
                 f"{_dec(r['used'] or 0)} / {r['total']:.0f} Go" if r["total"] else ""),
                ("Mémoire graphique", vr["used"], vr["total"], vr["iris"],
                 f"{_dec((vr['used'] or 0) / 1024)} / {vr['total'] / 1024:.0f} Go" if vr["total"] else "")]
        self.mem.set("–" if r["iris_go"] is None else f"{_dec(r['iris_go'])} Go", rows)
        n = len(v["cores"])
        self.cores.set(f"{n} cœurs" if n else "–", v["cores"])
        self.threads.set("", v["threads"])
        self.models.setText("&nbsp;&nbsp;&nbsp;".join(
            f"<span style='color:{IRIS if ok else HOME['off']}'>●</span> {name} "
            f"<span style='color:{HOME['texte2']}'>{state}</span>" for name, state, ok in v["models"])
            if v["measured"] else "")
