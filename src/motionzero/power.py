"""« iris réveil » (ou « iris wake ») rallume l'écran éteint. Iris ne touche jamais à la mise en veille du PC
(choix de l'utilisateur) : en veille complète, Iris est arrêtée par Windows et ne peut pas l'en sortir."""
import ctypes
import logging

log = logging.getLogger(__name__)

ES_DISPLAY_REQUIRED = 0x00000002
MOUSEEVENTF_MOVE = 0x0001


def wake_screen(kernel32=None, user32=None):
    """Rallume l'écran : demande d'affichage + un mouvement de souris nul (ce que Windows écoute vraiment)."""
    try:
        k = kernel32 or ctypes.windll.kernel32
        u = user32 or ctypes.windll.user32
        k.SetThreadExecutionState(ES_DISPLAY_REQUIRED)   # ponctuel : la minuterie de l'écran repart normalement
        u.mouse_event(MOUSEEVENTF_MOVE, 1, 0, 0, 0)
        u.mouse_event(MOUSEEVENTF_MOVE, -1, 0, 0, 0)
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
