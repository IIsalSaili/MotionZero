"""Pont vers VS Code : l'extension « Iris (pont) » (dossier pont-vscode/) lance les commandes de VS Code.

Pas de touche simulée : la commande marche où que soit le focus (panneau Claude compris), et la réponse dit si
l'effet a vraiment eu lieu. Installer / mettre à jour l'extension : tools/installer_pont.py.
"""
import json
import logging
import urllib.error
import urllib.request

PORT = 47613
TIMEOUT_S = 0.6
_log = logging.getLogger("motionzero")


def command(name):
    """Lance `name` (« next » / « prev ») dans VS Code.
    Renvoie (True, libellé de l'onglet) ou (False, raison) ; None si le pont ne répond pas (extension absente,
    VS Code fermé) : l'appelant se rabat alors sur l'ancienne méthode."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/{name}", timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as e:
        _log.info("pont VS Code injoignable (%s)", e)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("ok"):
        return True, str(data.get("label", ""))
    return False, str(data.get("reason", "echec"))
