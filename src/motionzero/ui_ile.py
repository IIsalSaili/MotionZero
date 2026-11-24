"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52)."""
import ctypes
import os as _os
import math
import random as _random

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget



def chip_rows(width, chips, max_w, gap=6, pad=18, max_rows=2):
    """Étiquettes rangées en lignes de largeur max_w (au plus max_rows lignes ; trop longue : coupée). Pur."""
    rows, cur, x = [], [], 0.0
    for c in chips:
        w = width(c) + pad
        if cur and x + w > max_w:
            rows.append(cur)
            cur, x = [], 0.0
        if w > max_w:
            continue
        cur.append(c)
        x += w + gap
    if cur:
        rows.append(cur)
    return rows[:max_rows] or [[]]

_FONT_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                          "assets", "fonts")
ISLAND_TOP = 12          # px depuis le haut de l'écran
ANSWER_W = 560           # largeur de l'île agrandie pour une réponse de Claude
ANSWER_MAX_H = 640      # 3 phrases longues tiennent ; au-delà, le texte est coupé proprement
ISLAND_H = 46
ISLAND_MAX_W = 960
ISLAND_FADE_S = 3.0      # sans rien de nouveau : l'île s'estompe…
ISLAND_FADED = 0.25      # … à 25 % d'opacité
TOAST_S = 4.0            # durée d'affichage d'une commande comprise / ignorée (ligne du bas, le temps de défiler)
TICKER_W = 460           # largeur de la ligne du bas
TICKER_H = 30
TICKER_SPEED = 60.0      # px/s quand le texte est trop long
TICKER_PAUSE_S = 0.8
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


CAM_BOX = 56             # caméra barrée (panne), en bas à gauche
CAM_MARGIN = 18
CAM_BLINK_S = 1.2        # période du clignotement (moins de 3 fois par seconde)


def cam_blink(now, motion=True):
    """Opacité de l'icône caméra : pleine puis presque éteinte ; fixe sans animations Windows. Pur."""
    if not motion:
        return 1.0
    return 1.0 if (now % CAM_BLINK_S) < CAM_BLINK_S * 0.6 else 0.25


APP_LABELS = {"chrome.exe": "CHROME", "code.exe": "VS CODE", "discord.exe": "DISCORD", "msedge.exe": "EDGE",
              "firefox.exe": "FIREFOX", "windowsterminal.exe": "TERMINAL", "notepad.exe": "BLOC-NOTES",
              "explorer.exe": "", "winword.exe": "WORD", "excel.exe": "EXCEL", "spotify.exe": "SPOTIFY",
              "whatsapp.exe": "WHATSAPP", "steam.exe": "STEAM"}


def app_label(exe):
    """Nom court de l'appli devant ; vide pour le bureau / l'explorateur ou rien. Pur : testable."""
    if not exe:
        return ""
    exe = exe.lower()
    if exe in APP_LABELS:
        return APP_LABELS[exe]
    name = exe[:-4] if exe.endswith(".exe") else exe
    return name.upper()[:14]


FLAG_ORDER = ("AGRIPPE", "SOURIS", "CANDIDATURE", "FOCUS", "BYPASS")   # le plus important d'abord


def island_text(st):
    """(haut, ligne du bas ou None, actif ?) d'après l'état du moteur. Pur : testable.
    #18 / #27 (demande de l'utilisateur, 24/11) : en haut, un ou deux mots fixes (le mode, plus l'état le plus
    important) ; en bas, une ligne courte qui défile : le dernier retour, sinon les autres états allumés
    (focus, bypass… restent visibles, jamais éteints en silence)."""
    base = MODE_NAMES.get(st.get("mode"), st.get("mode") or "")
    if base == "NEUTRE":                       # 24/11 : l'appli devant (Chrome, VS Code…), sinon rien
        base = app_label(st.get("front"))
    on = {"SOURIS": st.get("mouse"), "FOCUS": st.get("focus"), "BYPASS": st.get("bypass"),
          "CANDIDATURE": st.get("candidature"), "AGRIPPE": st.get("dragging")}
    flags = [f for f in FLAG_ORDER if on[f]]
    shown = flags[:1] if base else flags[:2]
    top = " · ".join(([base] if base else []) + shown)
    rest = " · ".join(f.lower() for f in flags if f not in shown) or None
    head = st.get("pointer") == "tete"
    phase = (st.get("qa") or {}).get("phase")
    pending = (st.get("reminders") or {}).get("pending")
    for cond, text in (
            (phase == "listening", "Ta question"), (phase == "thinking", "Iris réfléchit…"),
            (phase == "searching", "Recherche sur internet…"), (phase == "answer", "Iris répond"),
            (phase == "error", "Question : échec"),
            (st.get("dictating"), "Claude écoute"), (st.get("typing"), "Dictée"),
            (st.get("confirming"), f"{pending} · envoie ?" if pending else "Envoie ou annule"),
            (st.get("listening"), "Écoute"),
            (st.get("lost") and st.get("mouse"), "Visage perdu" if head else "Main perdue"),
            (st.get("arming"), "Tête de face" if head else "Main au centre")):
        if cond:
            return top, text, True
    toast, age = st.get("toast"), st.get("toast_age", 1e9)
    if toast and age <= TOAST_S:
        return top, toast, True
    return top, rest, False


def ticker_offset(text_w, room, elapsed, speed=TICKER_SPEED, pause=TICKER_PAUSE_S):
    """Décalage du texte de la ligne du bas : 0 s'il tient ; sinon il défile, puis repart après une pause. Pur."""
    if text_w <= room:
        return 0.0
    run = (text_w - room) / speed
    k = elapsed % (pause + run + pause)
    if k < pause:
        return 0.0
    return -min((k - pause) * speed, text_w - room)


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
        for name, color in (("mic-off", DISCORD_RED), ("headphone-off", DISCORD_RED), ("bell", "#FFFFFF"), ("clock", "#FFFFFF"), ("timer", "#FFFFFF"),
                            ("camera-off", "#FFFFFF")):
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
        if getattr(self, "cam_down", False) or getattr(self, "cam_gone", False):   # caméra barrée, en bas à gauche
            self.cam_gone = False
            r = r.united(QRect(0, int(self.height - CAM_BOX - 2 * CAM_MARGIN), CAM_BOX + 2 * CAM_MARGIN,
                               CAM_BOX + 2 * CAM_MARGIN))
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
        down = bool(st.get("cam_down"))
        if getattr(self, "cam_down", False) and not down:
            self.cam_gone = True               # caméra revenue : repeindre le coin une fois pour l'effacer
        if down != getattr(self, "cam_down", False):
            self.last_change = now
        self.cam_down = down
        panel = st.get("cand_panel")
        if getattr(self, "panel", None) and not panel:
            self.panel_gone = True             # mode éteint : repeindre la droite une fois pour l'effacer
        self.panel = panel
        if panel:
            active = True
        content = (mode, msg, (qa.get("phase"), qa.get("answer"), int(qa.get("left", 0))) if self.qa else None,
                   rem_key, self.next_rem, tuple(self.timer_pills), self.quota, repr(panel) if panel else None)
        if content != self.content:
            if not self.content or content[1] != self.content[1]:
                self.ticker_t0 = now           # nouveau texte en bas : il défile depuis le début
            self.content, self.last_change = content, now
        self.now = now
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
        scrolling = False
        if self.content and self.content[1] and self.motion:
            scrolling = QFontMetrics(self.font_small).horizontalAdvance(self.content[1]) > TICKER_W - 40
        return moving or (ringing and self.motion) or scrolling or getattr(self, "cam_down", False)

    def paint(self, p):
        if not self.content:
            return
        self._paint_main(p)
        if getattr(self, "quota", None):
            self._paint_quota(p, self.quota)
        if getattr(self, "panel", None):
            self._paint_cand_panel(p, self.panel)
        if getattr(self, "cam_down", False):
            self._paint_cam_down(p)

    def _paint_cam_down(self, p):
        """Caméra en panne : caméra barrée en bas à gauche, qui clignote (pas de texte, 24/11)."""
        x, y = CAM_MARGIN, self.height - CAM_MARGIN - CAM_BOX
        k = cam_blink(getattr(self, "anim_now", 0.0), self.motion)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 220))
        p.drawRoundedRect(QRectF(x, y, CAM_BOX, CAM_BOX), CAM_BOX / 2, CAM_BOX / 2)
        icon = self.icons.get("camera-off")
        if icon is not None:
            p.setOpacity(k)
            m = CAM_BOX * 0.24
            icon.render(p, QRectF(x + m, y + m, CAM_BOX - 2 * m, CAM_BOX - 2 * m))
        p.restore()

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
        extra = pn.get("extra") or []
        rows = (len(words) + 1) // 2
        bottom = PANEL_MARGIN + h - 22
        foot_y = bottom - 20
        p.setPen(QColor(138, 142, 154))
        p.setFont(small)
        p.drawText(QRectF(x, foot_y, inner, 20), Qt.AlignmentFlag.AlignCenter, pn.get("foot") or "")
        # autres mots de l'étape : une ligne chacun, « mots » à gauche, effet à droite
        fm_s = QFontMetrics(small)
        ex_y = foot_y - 10 - len(extra) * 42
        bold_s = QFont(small)
        bold_s.setBold(True)
        for k, (mots, quoi) in enumerate(extra):  # le mot en blanc, dessous ce qu'il fait
            ry = ex_y + k * 42
            p.setPen(white)
            p.setFont(bold_s)
            p.drawText(QRectF(x, ry, inner, 20), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(bold_s).elidedText(mots, Qt.TextElideMode.ElideRight, int(inner)))
            p.setPen(grey)
            p.setFont(small)
            p.drawText(QRectF(x, ry + 19, inner, 20), Qt.AlignmentFlag.AlignVCenter,
                       fm_s.elidedText(quoi, Qt.TextElideMode.ElideRight, int(inner)))
        if extra:
            p.setPen(QColor(138, 142, 154))
            p.drawText(QRectF(x, ex_y - 26, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Aussi")
            ex_y -= 34
        th = 86                                    # bouton : le mot, et dessous ce qu'il fait
        grid_h = rows * th + max(rows - 1, 0) * 8
        grid_y = ex_y - 8 - grid_h
        if words:
            p.setPen(QColor(138, 142, 154))
            p.drawText(QRectF(x, grid_y - 24, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Tu peux dire")
            ww = (inner - 8) / 2
            for k, (w, quoi) in enumerate(words):
                r = QRectF(x + (k % 2) * (ww + 8), grid_y + (k // 2) * (th + 8), ww, th)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(CAND if k == 0 else chip)
                p.drawRoundedRect(r, 10, 10)
                p.setPen(QColor(11, 11, 14) if k == 0 else white)
                p.setFont(word)
                p.drawText(QRectF(r.x(), r.y() + 8, ww, 26), Qt.AlignmentFlag.AlignCenter, w)
                p.setPen(QColor(30, 50, 44) if k == 0 else grey)
                p.setFont(small)
                p.drawText(QRectF(r.x() + 8, r.y() + 34, ww - 16, th - 38),
                           int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                           quoi)
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
                return 32 * len(chip_rows(QFontMetrics(small).horizontalAdvance, item[1], cw)) - 6
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
            elif it[0] == "chips":                # sur plusieurs lignes si besoin (#64 : ville, télétravail, salaire)
                fm = QFontMetrics(small)
                for row in chip_rows(fm.horizontalAdvance, it[1], cw):
                    px = cx
                    for c in row:
                        cwid = fm.horizontalAdvance(c) + 18
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(chip)
                        p.drawRoundedRect(QRectF(px, cy, cwid, 26), 13, 13)
                        p.setPen(white)
                        p.setFont(small)
                        p.drawText(QRectF(px, cy, cwid, 26), Qt.AlignmentFlag.AlignCenter, c)
                        px += cwid + 6
                    cy += 32
                cy -= 6
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
        fm_mode, fm_msg = QFontMetrics(self.font_mode), QFontMetrics(self.font_small)
        pad, dot, dgap = 22, 8, 10
        mode_w = (dot + dgap + fm_mode.horizontalAdvance(mode)) if mode else 0
        msg_w = fm_msg.horizontalAdvance(msg) if msg else 0
        w = 2 * pad + max(mode_w, min(msg_w, TICKER_W - 2 * pad)) if (mode or msg) else 0
        two = bool(mode and msg)                 # #18 : la même île s'agrandit, le texte sous les mots
        h = ISLAND_H + 20 if two else ISLAND_H
        gx = (self.width - (ISLET + (ISLET_GAP + w if w else 0))) / 2   # rien à dire : le logo seul, centré
        x, y = gx + ISLET + ISLET_GAP, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)       # le logo ne s'estompe jamais
        if w:
            p.setOpacity(self.opacity)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 235))                # noir opaque : lisible sur tout fond
            r = min(h, ISLAND_H) / 2
            p.drawRoundedRect(QRectF(x, y, w, h), r, r)
            line1 = (y + 7, 26) if two else (y, ISLAND_H)    # (haut, hauteur) de la ligne des mots
            if mode:
                mx = x + (w - mode_w) / 2                    # pastille + mots, centrés ensemble
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(QPointF(mx + dot / 2, line1[0] + line1[1] / 2), dot / 2, dot / 2)
                p.setPen(QColor(255, 255, 255))
                p.setFont(self.font_mode)
                p.drawText(QRectF(mx + dot + dgap, line1[0], fm_mode.horizontalAdvance(mode) + 2, line1[1]),
                           Qt.AlignmentFlag.AlignVCenter, mode)
            if msg:
                top, hh = (y + 33, 22) if two else (y, ISLAND_H)
                self._paint_ticker(p, x + pad, top, w - 2 * pad, msg, hh)
        p.restore()
        ty = y + h + CLOCK_GAP
        self._paint_clock(p, x, ty)
        if self.next_rem:
            ty += ISLAND_H + CLOCK_GAP
        tx = x
        for text, countdown in getattr(self, "timer_pills", []):
            tx += self._paint_timer_pill(p, tx, ty, text, countdown) + CLOCK_GAP

    def _paint_ticker(self, p, x, y, room, text, h=TICKER_H):
        """Ligne sous les mots, dans l'île : petite, centrée ; défile si elle est trop longue (#18)."""
        fm = QFontMetrics(self.font_small)
        tw = fm.horizontalAdvance(text)
        p.save()
        p.setClipRect(QRectF(x, y, room, h))
        p.setPen(QColor(255, 255, 255, 190))
        p.setFont(self.font_small)
        if tw <= room:
            p.drawText(QRectF(x, y, room, h), Qt.AlignmentFlag.AlignCenter, text)
        elif not self.motion:
            p.drawText(QRectF(x, y, room, h), Qt.AlignmentFlag.AlignCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, int(room)))
        else:
            off = ticker_offset(tw, room, getattr(self, "now", 0.0) - getattr(self, "ticker_t0", 0.0))
            p.drawText(QRectF(x + off, y, tw + 4, h), Qt.AlignmentFlag.AlignVCenter, text)
        p.restore()

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
