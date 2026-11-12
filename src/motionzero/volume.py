"""« iris volume » puis une phrase : régler le volume de Windows à la voix.

Exemples : « 40 », « 40 % », « à fond », « plus fort », « moins fort », « coupe », « remets le son ».
"""
import logging
import re

from .timers import _norm, _number

import time

log = logging.getLogger(__name__)
SHOW_S = 4.0                  # la barre reste affichée 4 s après le dernier réglage


class VolumeView:
    """Ce que la barre de volume affiche. Écrit par les fils « volume », lu par la boucle (jamais Core)."""

    def __init__(self):
        self.level, self.muted, self.until = None, False, -1e9

    def show(self, level, muted, now=None):
        self.level, self.muted = level, muted
        self.until = (now if now is not None else time.perf_counter()) + SHOW_S

    def state(self, t, listening=False):
        """{"level", "muted"} à afficher, ou None. Pendant l'écoute de « iris volume », toujours visible."""
        if self.level is None or not (listening or t < self.until):
            return None
        return {"level": self.level, "muted": self.muted}


VIEW = VolumeView()
STEP = 10                     # « plus fort » / « moins fort » : ±10 points

_UP = ("plus fort", "monte", "augmente", "plus")
_DOWN = ("moins fort", "baisse", "diminue", "moins")
_MUTE = ("coupe", "muet", "mute", "silence", "eteins")
_UNMUTE = ("remets", "rallume", "reactive", "demute", "unmute")
_MAX = ("a fond", "maximum", "max")


def _value(words):
    """Premier nombre de la phrase (chiffres ou lettres, 0 à 100), ou None."""
    for i in range(len(words)):
        w = words[i]
        if w == "cent":
            return 100
        if w == "soixante" and i + 1 < len(words) and words[i + 1] == "dix":
            return 70
        if w == "quatre" and i + 1 < len(words) and words[i + 1] in ("vingt", "vingts"):
            return 90 if i + 2 < len(words) and words[i + 2] == "dix" else 80
        if w in ("un", "une"):            # « baisse un peu » : pas « 1 % »
            continue
        v, n = _number(words, i)
        if v is not None:
            return v
    return None


def parse_volume(text):
    """Phrase -> ("set", 0..100) | ("delta", ±n) | ("mute",) | ("unmute",) | None (rien compris)."""
    t = " " + _norm(text).replace("%", " ") + " "
    words = t.split()
    if not words:
        return None
    v = _value(words)
    if v is not None:
        return ("set", max(0, min(100, v)))
    if any(f" {k} " in t for k in _MAX):
        return ("set", 100)
    if any(f" {k} " in t for k in _UNMUTE):
        return ("unmute",)
    if any(f" {k} " in t for k in _MUTE):
        return ("mute",)
    if any(f" {k} " in t for k in _UP):
        return ("delta", STEP)
    if any(f" {k} " in t for k in _DOWN):
        return ("delta", -STEP)
    return None


class WindowsVolume:
    """Volume principal des haut-parleurs par défaut (Core Audio, via pycaw). À utiliser dans un seul fil."""

    def _endpoint(self):
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetSpeakers().EndpointVolume

    def read(self):
        """(volume 0..100, coupé ?) des haut-parleurs par défaut."""
        import comtypes
        comtypes.CoInitialize()
        try:
            ev = self._endpoint()
            return round(ev.GetMasterVolumeLevelScalar() * 100), bool(ev.GetMute())
        finally:
            comtypes.CoUninitialize()

    def apply(self, cmd):
        """Applique la commande ; renvoie le texte à afficher."""
        import comtypes
        comtypes.CoInitialize()          # appelé depuis un fil de travail : COM doit y être initialisé
        try:
            ev = self._endpoint()
            if cmd[0] == "mute":
                ev.SetMute(1, None)
                VIEW.show(round(ev.GetMasterVolumeLevelScalar() * 100), True)
                return "SON COUPE"
            if cmd[0] == "unmute":
                ev.SetMute(0, None)
                level = round(ev.GetMasterVolumeLevelScalar() * 100)
                VIEW.show(level, False)
                return f"SON REMIS ({level} %)"
            now = round(ev.GetMasterVolumeLevelScalar() * 100)
            target = cmd[1] if cmd[0] == "set" else now + cmd[1]
            target = max(0, min(100, target))
            ev.SetMasterVolumeLevelScalar(target / 100, None)
            if target > 0:
                ev.SetMute(0, None)          # régler un volume rallume le son s'il était coupé
            VIEW.show(target, target == 0 and bool(ev.GetMute()))
            return f"VOLUME {target} %"
        finally:
            comtypes.CoUninitialize()


def volume_peek(device=None, view=None):
    """Fil « volume » : lit le volume actuel pour l'afficher dès « iris volume »."""
    view = view or VIEW
    try:
        level, muted = (device or WindowsVolume()).read()
    except Exception:
        log.exception("lecture du volume")
        return
    view.show(level, muted)


def volume_spoken(audio, transcribe, on_message, device=None):
    """Fil « volume » : transcrit, comprend, applique ; le résultat passe par on_message (jamais Core ici)."""
    try:
        text = (transcribe(audio) or "").strip(" .")
    except Exception:
        log.exception("transcription volume")
        text = ""
    if not text:
        on_message("RIEN ENTENDU : volume inchange")
        return
    cmd = parse_volume(text)
    log.info("volume : %r -> %s", text, cmd)
    if cmd is None:
        on_message(f"VOLUME : pas compris « {text} »")
        return
    try:
        on_message((device or WindowsVolume()).apply(cmd))
    except Exception:
        log.exception("reglage du volume")
        on_message("VOLUME : reglage impossible")
