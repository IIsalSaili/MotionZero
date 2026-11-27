"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52).
"""
import os as _os
import random as _random

from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from .ui_ile_base import (ALARM_RED, ANSWER_MAX_H, ANSWER_W, BAND_HALF_W, BLINK_EVERY, BLINK_S, BLUE, CAL_H, CAL_W, CAND, CLOCK_ANIM_S, CLOCK_BIG, CLOCK_GAP, DAYS, DISCORD_RED, EYE_AT, EYE_IN_ISLET, EYE_W, GAUGE_MARGIN, GAUGE_W, GHOST_S, GREEN, HELP_H, HELP_W, ICON, ISLAND_FADED, ISLAND_FADE_S, ISLAND_H, ISLAND_MAX_W, ISLAND_TOP, ISLET, ISLET_GAP, MIN_PT, MODE_NAMES, CORNER_W, OK_FLASH_S, ORANGE, PANEL_BOTTOM, PANEL_MARGIN, PANEL_W, REMINDER_W, RING_BLINK_S, RING_BY_MODE, RING_DEFAULT, SUBS_BOTTOM, SUBS_H, SUBS_W_FRAC, TICKER_H, TICKER_PAUSE_S, TICKER_SPEED, TICKER_W, TOAST_S, VOL_H, VOL_MARGIN, VOL_W, _FONT_DIR, _ICON_DIR, _LOGO_DIR, _ease, _ghost_box, chip_rows, clock_anim, clock_text, discord_icons, fit_font, gauge_geometry, ghost_geometry, islet_logo, islet_ring, paint_subs, paint_volume, reminder_texts, reminder_view, subs_rect, subs_text, volume_fill, volume_rect, windows_animations)  # noqa: F401
from .ui_ile_base2 import (APP_LABELS, CAM_BLINK_S, CAM_BOX, CAM_MARGIN, CLAUDE_ORANGE, FLAG_ORDER, HomeLogo, QUOTA_MARGIN, app_label, cam_blink, island_text, load_fonts, paint_claude_logo, paint_logo, ticker_offset)  # noqa: F401
from .ui_ile_panneau import PanneauMixin
from .ui_ile_cartes import CartesMixin
from .ui_ile_calendrier import CalendrierMixin
from .ui_ile_pieces import PiecesMixin


class _IslandPainter(PanneauMixin, CartesMixin, CalendrierMixin, PiecesMixin):
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
        for name in ("neutre", "neutre_ferme", "souris", "souris_ferme", "ok"):
            pm = QPixmap(_os.path.join(_LOGO_DIR, f"{name}.png"))
            if not pm.isNull():
                self.logos[name] = pm
        self.logo = None
        self.ring = (RING_DEFAULT, 2.0)
        self.flash_t0 = None
        self.icons = {}
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        for name, color in (("mic-off", DISCORD_RED), ("headphone-off", DISCORD_RED), ("bell", "#FFFFFF"), ("clock", "#FFFFFF"), ("timer", "#FFFFFF"), ("app-window", "#FFFFFF"),
                            ("camera-off", "#FFFFFF")):
            try:
                svg = open(_os.path.join(_ICON_DIR, f"{name}.svg"), encoding="utf-8").read()
                self.icons[name] = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode()))
            except OSError:
                pass
        self.rem = None          # ("plan" | "calendar" | "list", données) | None : au centre
        self.corner_rem = None   # rappel déclenché (dict) : coin haut droit
        self.timer_pills = []
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
        corner = bool(getattr(self, "corner_rem", None) or getattr(self, "timer_pills", None))
        if corner or getattr(self, "corner_gone", False):      # coin haut droit (ou à effacer)
            self.corner_gone = corner
            cw = CORNER_W + (PANEL_W + 2 * PANEL_MARGIN if getattr(self, "panel", None) else 0)
            r = r.united(QRect(int(self.width - cw), 0, int(cw), int(ISLAND_TOP + 3 * (ISLAND_H + CLOCK_GAP) + ANSWER_MAX_H)))
        if getattr(self, "panel", None) or getattr(self, "panel_gone", False):   # panneau candidature (ou à effacer)
            self.panel_gone = False
            r = r.united(QRect(int(self.width - PANEL_W - 2 * PANEL_MARGIN), 0, PANEL_W + 2 * PANEL_MARGIN,
                               int(self.height)))
        return r

    def update(self, st, now):
        mode, msg, active = island_text(st)
        qa = st.get("qa") or {}
        self.qa = qa if qa.get("phase") in ("answer", "error") else None
        self.rem = reminder_view(st, corner=True)
        cur = (st.get("reminders") or {}).get("current")
        self.corner_rem = cur or None          # rappel déclenché : coin haut droit, à côté de l'instruction
        self.help = st.get("help")
        tm = (st.get("reminders") or {}).get("timers") or {}
        self.timer_pills = [("Chrono " + tm["chrono"]["text"] + (" · arrêté" if tm["chrono"]["done"] else ""), False)] \
            if tm.get("chrono") else []
        if tm.get("timer"):
            self.timer_pills.append(("Timer " + tm["timer"]["text"], True))
        if self.timer_pills:
            active = True
        self.alttab = st.get("alttab")         # « iris alt-tab » : fenêtres numérotées, bandeau centré sous l'île
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
        if self.rem or self.help or self.alttab or self.corner_rem:
            active = True
        rem_key = ((self.rem[0], str(self.rem[1])) if self.rem else (("help", str(self.help["now"])) if self.help else None),
                   str(self.corner_rem) if self.corner_rem else None)
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
                   rem_key, self.next_rem, tuple(self.timer_pills), self.quota, repr(panel) if panel else None,
                   self.alttab)
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
        ringing = bool(self.corner_rem and self.corner_rem.get("ringing"))
        changed = (abs(target - self.opacity) > 0.01 or idle < 0.1 or logo != self.logo or ring != self.ring or ringing
                   or self.animating(now))
        self.opacity, self.logo, self.ring = target, logo, ring
        return changed

    def animating(self, now):
        """Vrai pendant l'animation du logo ou une alarme qui pulse : redessiner à 60 images/s."""
        moving = self.motion and self.clk_start is not None and (self.clk_end is not None or now - self.clk_start < CLOCK_ANIM_S)
        ringing = bool(self.corner_rem and self.corner_rem.get("ringing"))
        scrolling = False
        if self.content and self.content[1] and self.motion:
            scrolling = QFontMetrics(self.font_small).horizontalAdvance(self.content[1]) > TICKER_W - 40
        return moving or (ringing and self.motion) or scrolling or getattr(self, "cam_down", False)

    def paint(self, p):
        if not self.content:
            return
        self._paint_main(p)
        self._paint_corner(p)
        if getattr(self, "quota", None):
            self._paint_quota(p, self.quota)
        if getattr(self, "panel", None):
            self._paint_cand_panel(p, self.panel)
        if getattr(self, "cam_down", False):
            self._paint_cam_down(p)
