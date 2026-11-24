"""Constantes de Core : modes, mots, libellés, délais (découpé de core.py, #52)."""
import math
from .calendar_view import WORDS as CAL_WORDS  # noqa: F401  (réexporté pour Core)
from .cvgen import WORDS as CAND_WORDS  # noqa: F401



class Mode:
    DISABLED = "DESACTIVE"
    NEUTRAL = "NEUTRE"    # par défaut : la main ne déclenche rien, seule la voix agit
    READING = "LECTURE"
    MOUSE = "SOURIS"      # n'est plus un mode : un outil qui s'ajoute au mode en cours (voir Core.mouse)
    CHROME = "CHROME"     # commandes de navigation à la voix, tant que Chrome est devant (automatique, 14/11)
    IDLE = READING  # compatibilité : l'ancien « repos » est désormais la lecture


MENU_LABELS = {"left": "CLIC GAUCHE", "right": "CLIC DROIT", "up": "DOUBLE CLIC", "down": "SOURIS ETEINTE"}
WAKE_WORD = "iris"
VOICE_HOTKEYS = {"entrée": ["enter"], "space": ["space"], "copie": ["ctrl", "c"], "colle": ["ctrl", "v"],
                 "skip": ["right"], "back": ["left"],   # flèches : ±10 s sur YouTube
                 # texte et fenêtres (check-up du 13/11) ; en mode Chrome, « agrandis / réduis » restent le zoom
                 "sélection": ["ctrl", "a"], "coupe": ["ctrl", "x"], "efface": ["ctrl", "backspace"],
                 "réduis": ["win", "down"],
                 "undo": ["ctrl", "z"], "redo": ["ctrl", "y"],   # annuler / rétablir (#36) ; Ctrl+Y : Windows, VS Code
                 "gauche": ["win", "left"], "droite": ["win", "right"]}

# mode CHROME : mot dit (après « iris ») -> touches envoyées à Chrome, seulement s'il est au premier plan
CHROME_KEYS = {"retour": ["alt", "left"], "avance": ["alt", "right"],
               "suivant": ["ctrl", "tab"], "précédent": ["ctrl", "shift", "tab"],
               "onglet": ["ctrl", "t"], "ferme": ["ctrl", "w"], "rouvre": ["ctrl", "shift", "t"],
               "recharge": ["f5"],
               "descends": ["pagedown"], "monte": ["pageup"],
               "agrandis": ["ctrl", "plus"], "réduis": ["ctrl", "minus"],
               "zoom": ["ctrl", "plus"], "dézoom": ["ctrl", "minus"],     # 24/11 : mots dédiés, Chrome seulement
               "recherche": ["ctrl", "l"]}   # recherche : barre d'adresse puis dictée (comme « type »)
CHROME_LABELS = {"retour": "PAGE PRECEDENTE", "avance": "PAGE SUIVANTE", "suivant": "ONGLET SUIVANT",
                 "précédent": "ONGLET PRECEDENT", "onglet": "NOUVEL ONGLET", "ferme": "ONGLET FERME",
                 "rouvre": "ONGLET ROUVERT", "recharge": "PAGE RECHARGEE",
                 "descends": "PAGE BAS", "monte": "PAGE HAUT",
                 "agrandis": "ZOOM +", "réduis": "ZOOM -", "zoom": "ZOOM +", "dézoom": "ZOOM -", "recherche": "RECHERCHE : parle"}
CHROME_GRACE_S = 5.0      # « iris chrome » : le temps que Chrome s'ouvre avant de juger qu'il n'est pas devant
# fenêtres d'Iris (fenêtre invisible des raccourcis Discord, accueil, aide…) : ne comptent jamais comme
# « une autre appli devant » (14/11 : « iris mute » faisait quitter le mode Chrome, 53 « iris chrome » redits en 4 jours)
IRIS_EXES = ("python.exe", "pythonw.exe")

ALIASES = {"envoyé": "envoie"}   # « envoyé » vient plus naturellement (demande de l'utilisateur, 12/11)
           # « muet » et « espace » retirés le 19/11 (#50) : « mute » et « space » suffisent   # « ok / okay » retirés le 14/11 (jamais utilisés)
EDITOR_TABS = {"suivant": ["ctrl", "pagedown"], "précédent": ["ctrl", "pageup"]}   # VS Code (pas Ctrl+Tab :
                          # il ouvre une liste qui attend qu'on relâche Ctrl)
HELP_S = 90.0             # « iris aide » : fermée seule après ce temps
CAL_IDLE_S = 60.0         # calendrier ouvert sans commande : fermé
# après « iris skip / undo… », redits seuls sans « iris » pendant 2 s. 14/11 : + espace et suivant / précédent
# (onglets de VS Code), souvent redits avec « iris » (6 fois chacun en 4 jours) ; en Chrome ils sont déjà libres
TYPE_WAIT_S = 20.0        # « iris type » : attente maximale du texte (Whisper) avant d'abandonner la confirmation
TYPE_ERASE_S = 30.0       # « iris annule » dit après la confirmation : efface encore la dictée seule (pas tout le champ)
REPEATABLE = ("skip", "back", "efface", "undo", "redo", "space", "suivant", "précédent")
# mot dit -> ce qui se passe (affiché en grand, et dans le panneau d'aide)
VOICE_LABELS = {"clic": "CLIC GAUCHE", "double": "DOUBLE CLIC", "menu": "CLIC DROIT",
                "agrippe": "AGRIPPE : bouton tenu (redis AGRIPPE pour lacher)", "entrée": "TOUCHE ENTREE",
                "space": "TOUCHE ESPACE",
                "annule": "TOUCHE ECHAP", "copie": "COPIER (Ctrl+C)", "colle": "COLLER (Ctrl+V)",
                "claude": "MICRO CLAUDE : parle",
                "type": "DICTEE : parle",
                "tab": "FENETRE SUIVANTE (Alt+Tab)", "discord": "DISCORD", "chrome": "CHROME", "studio": "VS CODE", "accueil": "ACCUEIL MOTIONZERO",
                "mute": "DISCORD COUPE", "démute": "DISCORD RALLUME", "sourdine": "DISCORD SOURDINE", "souris": "SOURIS",
                "lecture": "LECTURE", "message": "MESSAGE DISCORD : salon puis texte",
                "salon": "SALON VOCAL : dis son nom", "silence": "LECTURE DISCORD COUPEE",
                "lis": "LECTURE DISCORD ACTIVE",
                "skip": "AVANCE (fleche droite)", "back": "RECULE (fleche gauche)",
                "sélection": "TOUT SELECTIONNE (Ctrl+A)", "coupe": "COUPER (Ctrl+X)", "efface": "MOT EFFACE",
                "undo": "ANNULE (Ctrl+Z)", "redo": "RETABLI (Ctrl+Y)",
"réduis": "FENETRE REDUITE",
                "gauche": "FENETRE A GAUCHE", "droite": "FENETRE A DROITE",
                "rappel": "RAPPEL : dis quand et quoi", "merci": "RAPPEL VALIDE",
                "plus tard": "RAPPEL DANS 10 MIN", "volume": "VOLUME : dis le niveau", "heure": "HEURE", "date": "DATE", "quota": "QUOTA CLAUDE", "focus": "FOCUS", "traducteur": "TRADUCTEUR"}
# « iris ouvre / ferme / message / salon » : ce qui est enregistré puis transcrit par Whisper
OPEN_STOP = {"open": "open_stop", "close": "close_stop", "message": "message_stop", "salon": "salon_stop",
             "rappel": "rappel_stop", "timer": "timer_stop",
             "volume": "volume_stop", "instruction": "instruction_stop", "candq": "candq_stop"}
OPEN_WAIT = {"candq": "QUESTION : je prépare la réponse…", "open": "OUVRE : je cherche l'appli…", "close": "FERME : je cherche l'appli…",
             "message": "MESSAGE : envoi au bot…", "salon": "SALON : je cherche…",
             "rappel": "RAPPEL : Iris reflechit…", "timer": "TIMER : je lis la duree…",
             "volume": "VOLUME : je regle…", "instruction": "INSTRUCTION : Iris reflechit…"}


# « iris + mot » sans état : une action, et un libellé (None = celui de VOICE_LABELS)
SIMPLE_ACTIONS = {"plein écran": (("window", "max"), "PLEIN ECRAN"),   # partout, Chrome compris
                  "agrandis": (("window", "max"), "PLEIN ECRAN"),      # hors mode Chrome (là : zoom)
                  "envoie": (("hotkey", ["enter"]), "TOUCHE ENTREE"),   # Entrée dans la fenêtre active
                  "annule": (("annule",), "ANNULE"),   # vide le message de Claude si VS Code est devant, sinon Échap
                  "tab": (("alt_tab",), None),
                  "réveil": (("wake",), "ECRAN RALLUME"),
                  "chronomètre": (("chrono",), "CHRONOMETRE"),
                  "plus tard": (("rappel_tard",), None),
                  "viens": (("bot_join",), "IRIS : J'ARRIVE EN VOCAL"),
                  "pars": (("bot_leave",), "IRIS QUITTE LE VOCAL"),
                  "silence": (("discord_hush",), None), "lis": (("discord_read",), None),
                  "mute": (("discord_mute",), None), "démute": (("discord_unmute",), None),
                  "sourdine": (("discord_deafen",), None)}
# focus, bypass, candidature : allumés jusqu'à ce que l'utilisateur les éteigne lui-même (19/11 : plus de minuteur)
CAND_IDLE_S = BYPASS_IDLE_S = FOCUS_IDLE_S = math.inf

# « iris + mot » avec de l'état : mot -> méthode Core._cmd_<nom>
COMMANDS = {"clic": "click", "double": "click", "menu": "click", "agrippe": "grip",
            "scroll": "scroll", "claude": "claude", "souris": "mouse", "question": "question", "ouvre": "open",
            "type": "type", "ferme": "close", "timer": "timer", "calendrier": "calendar",
            "heure": "clock", "date": "clock", "merci": "thanks",
            "message": "listen", "salon": "listen", "rappel": "listen", "volume": "listen",
            "instruction": "listen",   # « iris instruction » puis une demande libre (#45)
            "tête": "pointer", "main": "pointer", "centre": "center", "lecture": "reading",
            "discord": "app", "chrome": "app", "studio": "app", "accueil": "app", "pause": "pause",
            "aide": "help", "guide": "guide", "quota": "quota", "focus": "focus",
            "traducteur": "translator", "bypass": "bypass", "candidature": "candidature"}



def head_gain(speed, lo_speed, hi_speed, lo, hi):
    """Gain de la souris à la tête : courbe au carré entre les deux vitesses. Lent = très précis, longtemps ;
    l'accélération ne vient qu'avec un geste franc. Pur : testable."""
    k = min(max((speed - lo_speed) / max(hi_speed - lo_speed, 1e-6), 0.0), 1.0)
    return lo + (hi - lo) * k * k

