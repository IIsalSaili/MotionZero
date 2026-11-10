"""Raccourcis Discord lus sur le PC (au lieu d'être écrits en dur).

Discord les garde dans son « Local Storage » (%APPDATA%\\discord\\Local Storage\\leveldb), entrée
« keybinds » : {"_state": {"17": {"action": "TOGGLE_MUTE", "shortcut": [[0, 110, ...], [0, 107, ...]],
"enabled": true, ...}}}. Chaque touche est [type, code] : type 0 = clavier, code = code de touche Windows.

Seule l'entrée « keybinds » est lue (leveldb_mini ne décode que cette clé) : le reste de la base, dont le
jeton de connexion, n'est ni lu, ni gardé, ni envoyé.
"""
import json
import logging
import os

from .leveldb_mini import latest_value

log = logging.getLogger("motionzero.discord")
DB_DIR = os.path.expandvars(r"%APPDATA%\discord\Local Storage\leveldb")
FALLBACK = {"TOGGLE_MUTE": [0x6E, 0x6B]}      # Suppr/point + « + » du pavé numérique (ancien réglage)
_cache = {"mtime": None, "binds": {}}


def _db_mtime():
    try:
        return max(os.path.getmtime(os.path.join(DB_DIR, f)) for f in os.listdir(DB_DIR))
    except (OSError, ValueError):
        return None


def parse_keybinds(raw):
    """{action: [codes de touches]} pour les raccourcis clavier actifs. Pur : testable."""
    if raw is None:
        return {}
    text = raw[1:].decode("latin-1") if raw[:1] == b"\x01" else raw[1:].decode("utf-16-le")
    state = json.loads(text).get("_state", {})
    binds = {}
    for b in state.values():
        if not isinstance(b, dict) or not b.get("enabled", True):
            continue
        keys = [k[1] for k in b.get("shortcut", []) if isinstance(k, list) and len(k) >= 2 and k[0] == 0]
        if keys and b.get("action"):
            binds.setdefault(b["action"], keys)   # première occurrence d'une action
    return binds


def keybinds():
    """Raccourcis actuels de Discord, relus seulement si sa base a changé."""
    mtime = _db_mtime()
    if mtime is not None and mtime != _cache["mtime"]:
        try:
            binds = parse_keybinds(latest_value(DB_DIR, lambda k: k.endswith(b"keybinds")))
            _cache.update(mtime=mtime, binds=binds)
            log.info("raccourcis discord relus : %s", {a: k for a, k in binds.items() if a == "TOGGLE_MUTE"})
        except Exception:
            log.exception("raccourcis discord illisibles (on garde les precedents)")
    return _cache["binds"]


def combo(action):
    """Codes de touches pour une action Discord (« TOGGLE_MUTE »…), ou le réglage de secours."""
    keys = keybinds().get(action)
    if keys:
        return keys
    log.warning("raccourci discord %s introuvable : reglage de secours", action)
    return FALLBACK.get(action)
