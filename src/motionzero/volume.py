"""« iris volume » puis une phrase : régler le volume de Windows à la voix.

Exemples : « 40 », « 40 % », « à fond », « plus fort », « moins fort », « coupe », « remets le son ».
"""
import logging
import re

from .timers import _norm, _number

log = logging.getLogger(__name__)
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

    def apply(self, cmd):
        """Applique la commande ; renvoie le texte à afficher."""
        import comtypes
        comtypes.CoInitialize()          # appelé depuis un fil de travail : COM doit y être initialisé
        try:
            ev = self._endpoint()
            if cmd[0] == "mute":
                ev.SetMute(1, None)
                return "SON COUPE"
            if cmd[0] == "unmute":
                ev.SetMute(0, None)
                return f"SON REMIS ({round(ev.GetMasterVolumeLevelScalar() * 100)} %)"
            now = round(ev.GetMasterVolumeLevelScalar() * 100)
            target = cmd[1] if cmd[0] == "set" else now + cmd[1]
            target = max(0, min(100, target))
            ev.SetMasterVolumeLevelScalar(target / 100, None)
            if target > 0:
                ev.SetMute(0, None)          # régler un volume rallume le son s'il était coupé
            return f"VOLUME {target} %"
        finally:
            comtypes.CoUninitialize()


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
