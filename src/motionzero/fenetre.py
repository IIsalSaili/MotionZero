"""« iris plein écran » (et « iris agrandis » hors mode Chrome) : la fenêtre au premier plan prend tout l'écran.
Par l'API Windows et non Win+Haut : après « iris gauche », Win+Haut ne donne qu'un quart d'écran (13/11)."""
import ctypes
import logging

log = logging.getLogger(__name__)

SW_MAXIMIZE = 3


def maximize_foreground(user32=None):
    try:
        u = user32 or ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            log.warning("plein ecran : aucune fenetre au premier plan")
            return False
        u.ShowWindow(hwnd, SW_MAXIMIZE)
        return True
    except Exception:
        log.exception("plein ecran")
        return False


def window_actions(acts, maximize=maximize_foreground):
    """Traite ("window", "max") ; renvoie les autres actions."""
    rest = []
    for a in acts:
        if a[0] == "window":
            log.info("fenetre en plein ecran")
            maximize()
        else:
            rest.append(a)
    return rest
