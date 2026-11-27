"""Fonctions pures et petits fichiers de réglages de l'application (découpé de app.py, #52)."""
import ctypes
import logging
import os
import queue
import time



_log = logging.getLogger("motionzero")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIN = "motionzero"
DETECT_MAX_FPS = 20          # plafond de détection (moins de charge)
IDLE_DETECT_FPS = 5          # sans main depuis IDLE_AFTER_S (ou appli en pause) : détection ralentie
IDLE_AFTER_S = 2.0
STALE_S = 0.5                # sans image depuis 0,5 s : caméra considérée perdue


def lower_priority():
    """Priorité « inférieure à la normale » : un jeu ou une appli lourde passe toujours avant motionzero."""
    try:
        BELOW_NORMAL = 0x4000
        k32 = ctypes.windll.kernel32
        # handle typé : en entier simple, le « -1 » du processus courant était tronqué (appel sans effet)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL):
            raise OSError(ctypes.GetLastError())
    except Exception:
        logging.getLogger("motionzero").warning("priorite du processus non changee")




def watch_engine(live, stop, path, limit_s=10.0, period_s=2.0, clock=time.perf_counter, wait=None):
    """Boucle principale muette depuis plus de limit_s : la pile de tous les fils est écrite dans path (une
    fois par blocage) et signalée au journal. Sert à trouver ce qui la bloque, sans outil extérieur."""
    import faulthandler
    wait = wait or stop.wait
    reported = None
    while not wait(period_s):
        beat = live.get("beat")
        if beat is None:
            continue
        if clock() - beat < limit_s:
            reported = None
            continue
        if reported == beat:
            continue
        reported = beat
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n=== boucle principale bloquee depuis {clock() - beat:.0f} s ({time.ctime()}) ===\n")
                f.flush()
                faulthandler.dump_traceback(file=f, all_threads=True)
            _log.error("boucle principale bloquee depuis %.0f s : piles dans %s", clock() - beat, path)
        except Exception:
            _log.exception("surveillance de la boucle")


def drain(q):
    """Vide une file sans jamais bloquer. (13/11 : « while not q.empty() » sans get() tournait à l'infini
    après un clic sur « main / tête » : caméra figée, voix sans effet, mémoire qui gonfle.)"""
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


from . import parametres as _p                     # tous les choix dans parametres.json (26/11)
POINTER_FILE, QUOTA_FILE, CONV_FILE, QUIET_FILE = _p.POINTER, _p.QUOTA, _p.CONVERSATION, _p.QUIET


def top_shown(d, t):
    """Quelque chose est affiché en haut (réponse, rappel, liste) ? Pour « ferme » en mode Chrome (#34)."""
    try:
        qa = d.asker.snapshot() if d.asker is not None else None
        desk = getattr(d, "desk", None)
        rem = desk is not None and (bool(desk.r.active) or t < desk.list_until)
        ins = getattr(d, "instructeur", None)
        card = ins is not None and ins.state(t) is not None      # carte de l'instruction (aide, plan, résultat)
        return bool(qa) or bool(rem) or card
    except Exception:                          # #52 : jamais avalé en silence
        _log.exception("top_shown")
        return False


def plan_card(d, t):
    """Carte du haut : celle de l'instruction (« iris candidature » a son panneau à droite)."""
    for name in ("instructeur",):
        svc = getattr(d, name, None)
        card = svc.state(t) if svc is not None else None
        if card is not None:
            return card
    return None


def cand_panel(d, t):
    """Panneau de « iris candidature » (à droite), tant que le mode est allumé ; None sinon."""
    svc = getattr(d, "candidature", None)
    if svc is None or not d.core.cand_on(t):
        return None
    try:
        return svc.panel(t)
    except Exception:                          # le panneau ne doit jamais faire tomber la boucle
        _log.exception("panneau candidature")
        return None


def reminder_shown(d):
    """Un rappel est affiché ? Pour « plus tard » sans « iris »."""
    try:
        desk = getattr(d, "desk", None)
        return desk is not None and bool(desk.r.active)
    except Exception:
        _log.exception("reminder_shown")
        return False


VOLUME_FILE = _p.VOLUME   # volume des sons d'Iris, choisi dans l'accueil (#28)
VOLUME_STEPS = (0.3, 0.5, 0.7, 1.0)


def read_volume(path, default):
    try:
        value = float(path.read())
    except (TypeError, ValueError):
        return default
    return value if 0.0 <= value <= 1.0 else default


def next_volume(v):
    """Bouton de l'accueil : 30 -> 50 -> 70 -> 100 -> 30 %."""
    for s in VOLUME_STEPS:
        if s > v + 1e-6:
            return s
    return VOLUME_STEPS[0]


def last_tab(n):
    """« ferme » ne doit jamais fermer Chrome entier : 1 onglet (ou moins) = on ne touche à rien.
    Illisible (None) : on garde Ctrl+W, comme avant. Pur : testable."""
    return n is not None and n <= 1


def read_conversation(path):
    """Mode conversation enregistré ; coché par défaut (fichier absent ou illisible). Pur sauf la lecture."""
    return path.read() != "non"


def read_quiet(path):
    from .voice import QUIET_CHOICES
    value = path.read()
    return value if value in QUIET_CHOICES else "auto"


def next_quiet(choice):
    """Bouton de l'accueil : le soir -> toujours -> jamais -> le soir."""
    from .voice import QUIET_CHOICES
    return QUIET_CHOICES[(QUIET_CHOICES.index(choice) + 1) % 3] if choice in QUIET_CHOICES else "auto"


def read_pointer(path, default="main"):
    value = path.read()
    return value if value in ("main", "tete") else default


def write_pointer(path, value):
    path.write(value)   # échec : avertissement au journal, sans exception


def detect_period(disabled, last_hand_t, t):
    """Intervalle entre deux détections : pleine vitesse avec une main, ralenti sinon."""
    if disabled or t - last_hand_t >= IDLE_AFTER_S:
        return 1.0 / IDLE_DETECT_FPS
    return 1.0 / DETECT_MAX_FPS


CONFIRM_WORDS = frozenset({"envoie", "envoyé", "annule", "oui"})


# dernière erreur à montrer dans l'îlot (#51) : écrite par la boucle, les crochets d'erreur et les fils,
# lue seulement par la boucle principale (pas d'état de Core touché)
ERROR_NOTICE = {"t": [], "notice": None}


def note_error(where):
    """Retient une erreur pour l'îlot : « ERREUR » simple, « ERREUR REPETEE » si 5 en moins de 10 s."""
    t = time.perf_counter()
    ts = [x for x in ERROR_NOTICE["t"] if t - x < 10.0][-4:] + [t]
    ERROR_NOTICE["t"] = ts
    text = ("ERREUR REPETEE (%s) : dis STOP puis reessaie, sinon relance Iris" if len(ts) >= 5
            else "ERREUR (%s) : la commande n'a pas marche") % where
    ERROR_NOTICE["notice"] = (text, t)


def cam_down(status):
    """Caméra en panne (perdue, en reconnexion) ; pas coupée exprès ni arrêtée. Pur : testable."""
    from .camera import LOST, RECONNECTING
    return status in (LOST, RECONNECTING)


def pick_toast(*items):
    """Le message le plus récent parmi (texte, instant) ou None."""
    items = [i for i in items if i]
    return max(items, key=lambda i: i[1]) if items else None




APP_ID = "Iris.motionzero"
ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "assets", "iris", "iris.ico")


def set_app_identity(app_id=APP_ID, shell32=None):
    """Barre des tâches : Iris à son nom et son logo, pas celui de Python. À appeler avant la 1re fenêtre.
    Renvoie False si Windows refuse (Iris continue, avec le logo de Python)."""
    try:
        if shell32 is None:
            import ctypes
            shell32 = ctypes.windll.shell32
        return shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
    except Exception:
        return False


def set_app_icon(qt, path=ICON_PATH):
    """Logo d'Iris sur toutes ses fenêtres (barre des tâches, Alt+Tab). Fichier absent : rien, sans erreur."""
    if not os.path.isfile(path):
        return False
    from PySide6.QtGui import QIcon
    qt.setWindowIcon(QIcon(path))
    return True


def make_tray(qt, on_click, path=ICON_PATH):
    """Icône d'Iris dans la zone de notification (en bas à droite) : un clic rouvre l'accueil.
    Renvoie l'icône (à garder en vie), ou None si Windows n'en a pas ou si le logo manque."""
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QSystemTrayIcon
        if not os.path.isfile(path) or not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(QIcon(path), qt)
        tray.setToolTip("Iris : clic pour ouvrir l'accueil")
        tray.activated.connect(lambda reason: on_click()
                               if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                                             QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        tray.show()
        return tray
    except Exception:
        logging.getLogger("motionzero").exception("icone de la zone de notification")
        return None
