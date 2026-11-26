"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52) : constantes et fonctions (1/2, découpé de ui_ile.py, #52)."""
import ctypes
import os as _os

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics


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
MODE_NAMES = {"NEUTRE": "NEUTRE", "SOURIS": "SOURIS", "CHROME": "CHROME", "DESACTIVE": "PAUSE"}

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
                data.get("meta") or "« oui » dans les 10 s : faire · sinon annulé · « stop » : arrêter")
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
