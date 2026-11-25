"""Interface Qt : fenêtre d'aperçu caméra et verre plein écran transparent aux clics.

Le moteur (caméra, MediaPipe, Core) tourne dans un autre fil et envoie ses images par Bridge.
Les signaux Qt émis depuis ce fil arrivent dans le fil de l'interface par la file d'attente Qt.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


from .ui_ile import (ALARM_RED, ANSWER_MAX_H, ANSWER_W, APP_LABELS, BAND_HALF_W, BLINK_EVERY, BLINK_S, BLUE, CAL_H, CAL_W, CAM_BLINK_S, CAM_BOX, CAM_MARGIN, CAND, CLAUDE_ORANGE, CLOCK_ANIM_S, CLOCK_BIG, CLOCK_GAP, DAYS, DISCORD_RED, EYE_AT, EYE_IN_ISLET, EYE_W, FLAG_ORDER, GAUGE_MARGIN, GAUGE_W, GHOST_S, GREEN, HELP_H, HELP_W, HomeLogo, ICON, ISLAND_FADED, ISLAND_FADE_S, ISLAND_H, ISLAND_MAX_W, ISLAND_TOP, ISLET, ISLET_GAP, MIN_PT, MODE_NAMES, OK_FLASH_S, ORANGE, PANEL_BOTTOM, PANEL_MARGIN, PANEL_W, QUOTA_MARGIN, REMINDER_W, RING_BLINK_S, RING_BY_MODE, RING_DEFAULT, SUBS_BOTTOM, SUBS_H, SUBS_W_FRAC, TICKER_H, TICKER_PAUSE_S, TICKER_SPEED, TICKER_W, TOAST_S, VOL_H, VOL_MARGIN, VOL_W, _FONT_DIR, _ICON_DIR, _IslandPainter, _LOGO_DIR, _ease, _ghost_box, app_label, cam_blink, chip_rows, clock_anim, clock_text, discord_icons, fit_font, gauge_geometry, ghost_geometry, island_text, islet_logo, islet_ring, load_fonts, paint_claude_logo, paint_logo, paint_subs, paint_volume, reminder_texts, reminder_view, subs_rect, subs_text, ticker_offset, volume_fill, volume_rect, windows_animations)  # noqa: F401
from .ui_accueil_fen import (HOME, MODE_COLORS_HOME, PreviewWindow, SENSOR_COLORS, TONE_COLORS, _FONT, _esc, _u32, last_html, now_html, sensors_html)  # noqa: F401
from .ui_verre import (EyeButton, GlassOverlay, HALO_W, KeySink, LOUPE_D, LOUPE_GAP, LOUPE_ZOOM, RING_R, RING_W, RepairButton, STOP_HAND_PAD, STOP_MARGIN, STOP_RED, STOP_SIZE, StopButton, _GWL_EXSTYLE, _WDA_EXCLUDEFROMCAPTURE, _WS_EX_LAYERED, _WS_EX_NOACTIVATE, _WS_EX_TOOLWINDOW, _WS_EX_TOPMOST, _WS_EX_TRANSPARENT, apply_overlay_style, set_capture_visible)  # noqa: F401

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
    conversation = Signal(bool)  # mode conversation coché / décoché -> bouton de l'accueil
    camera = Signal(bool)    # webcam coupée (True) / allumée -> bouton de l'accueil
    iris_volume = Signal(float)  # volume des sons d'Iris choisi -> bouton de l'accueil
    lecture = Signal(bool)   # lecture à voix haute cochée / décochée -> carte de l'accueil


