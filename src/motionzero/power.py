"""Veille de Windows. Un PC en veille complète ne fait plus tourner Iris (micro et caméra arrêtés) : rien ne
pourrait l'en sortir à la voix. Tant qu'Iris tourne, le PC ne s'endort donc pas ; seul l'écran s'éteint, et
« iris réveil » (ou « iris wake ») le rallume."""
import ctypes
import logging

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
MOUSEEVENTF_MOVE = 0x0001


def keep_system_awake(kernel32=None):
    """Empêche la mise en veille du PC (pas celle de l'écran) tant que le processus vit."""
    try:
        k = kernel32 or ctypes.windll.kernel32
        ok = k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if not ok:
            log.warning("impossible d'empecher la mise en veille")
        return bool(ok)
    except Exception:
        log.exception("mise en veille")
        return False


def wake_screen(kernel32=None, user32=None):
    """Rallume l'écran : demande d'affichage + un mouvement de souris nul (ce que Windows écoute vraiment)."""
    try:
        k = kernel32 or ctypes.windll.kernel32
        u = user32 or ctypes.windll.user32
        k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        u.mouse_event(MOUSEEVENTF_MOVE, 1, 0, 0, 0)
        u.mouse_event(MOUSEEVENTF_MOVE, -1, 0, 0, 0)
        k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)   # l'écran pourra se rééteindre plus tard
        return True
    except Exception:
        log.exception("reveil de l'ecran")
        return False


def power_actions(acts, wake=wake_screen):
    """Traite ("wake",) ; renvoie les autres actions."""
    rest = []
    for a in acts:
        if a[0] == "wake":
            log.info("reveil de l'ecran demande")
            wake()
        else:
            rest.append(a)
    return rest
