"""Machine à états, gestes v2 : aucune pose de doigts, aucun pincement.
Seules informations utilisées : présence de la main, centre de la paume, mouvement, immobilité.

Modes :
  LECTURE : paume au bord droit / gauche de l'image = page suivante / précédente.
            Main immobile 1,5 s -> bulle « SOURIS ? » ; petit mouvement vers le haut = confirmer.
  SOURIS  : le curseur suit les mouvements de la main (relatif, comme un pavé tactile).
            Main immobile 0,8 s -> menu à 4 directions :
              gauche = clic gauche, droite = clic droit, haut = double clic, bas = retour lecture.
            Main absente 2 s -> retour lecture.
  DESACTIVE : bouton STOP ou « iris pause » ; « iris reprise » pour revenir.

Actions renvoyées :
  ("mode", nom) ; ("key", nom) ; ("move", x, y) ; ("click", "left"|"right") ; ("release_all",)
"""
from collections import deque

from .filters import OneEuro
from .gestures import RadialMenu, ScrollDetector, StillnessDetector, ZoneDetector
from .head import HeadPointer
from .poses import PoseVoter
from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401
from .core_voix import VoixMixin
from .core_commandes import CommandesMixin
from .core_ecoute import EcouteMixin
from .core_main import MainMixin
from .core_defilement import DefilementMixin


class Core(MainMixin, DefilementMixin, VoixMixin, CommandesMixin, EcouteMixin):
    # Chaque action reconnue (geste ou voix) passe par last_gesture : on la garde aussi dans l'historique
    # affiché sous la caméra, pour vérifier en simulation que la commande « aurait eu lieu ».
    @property
    def last_gesture(self):
        return self._last_gesture

    @last_gesture.setter
    def last_gesture(self, value):
        self._last_gesture = value
        if value:
            self.feed.append(value)

    def __init__(self, cfg, screen=(0, 0, 1920, 1080)):
        self.feed = deque(maxlen=6)
        self._last_gesture = None
        self.cfg = cfg
        self.screen = screen
        self.mode = cfg.start_mode
        # souris : un outil, pas un mode. « iris souris » dans Chrome garde le mode Chrome (demande, 12/11)
        self.mouse = False
        # ce qui pilote la souris : la main ou la tête (choix retenu par l'appli, voir app.POINTER_FILE)
        self.pointer = cfg.pointer if cfg.pointer in ("main", "tete") else "main"
        self.head = HeadPointer(cfg.head_scale, cfg.head_scale_y)
        if self.mode == Mode.MOUSE:
            self.mode, self.mouse = Mode.NEUTRAL, True
        self.mode_since = -1e9
        self.mode_why = "démarrage"
        self.mode_auto = False
        self.chrome_seen = False
        self.last_seen = None
        self.released = True
        self.features = None
        self.pose = None
        self.last_gesture = None  # (texte, t)
        sx, sy, sw, sh = screen
        self.cursor = (sx + sw // 2, sy + sh // 2)
        self._cursor_f = [float(self.cursor[0]), float(self.cursor[1])]
        self.still = StillnessDetector(cfg)
        self.zone = ZoneDetector(cfg)
        self.scroll = ScrollDetector(cfg)
        self.scroll_progress = 0.0
        self.scroll_side = None
        self.menu = RadialMenu(cfg)
        self.fx = OneEuro(cfg.palm_min_cutoff, cfg.palm_beta)
        self.fy = OneEuro(cfg.palm_min_cutoff, cfg.palm_beta)
        self.prev_palm = None
        self.prev_t = None
        self.bubble = None          # (t0, x0, y0) quand la bulle « SOURIS ? » est affichée
        self.need_move = False      # après une bulle ignorée : bouger avant d'en revoir une
        self.travel = 0.0           # déplacement du curseur depuis le dernier menu (px)
        self.last_click_t = -1e9
        self.cursor_hist = deque(maxlen=90)   # (t, curseur) : pour cliquer là où l'on visait
        self.wake_t = -1e9                    # début du dernier « iris » entendu
        self.freeze_until = -1e9              # curseur figé (de « iris » à la commande) : clic vocal précis
        self.head_speed = 0.0                 # souris à la tête : vitesse moyennée (voir _head_speed)
        self.head_speeds = deque(maxlen=200)  # pour le journal de réglage
        self.dragging = False                 # bouton tenu par « glisse » : « lâche » toujours écouté
        self.pose_cents = None                # repères de poses de l'utilisateur (calibration/poses.json)
        self.pose_voter = PoseVoter()
        self.pose_firm = None                 # dernière pose sûre (ouverte / fermée / index)
        self.point_frames = 0                 # images de suite main ouverte
        self.closed_frames = 0                # images de suite main fermée
        self.pressing = False                 # bouton gauche enfoncé (main gardée ouverte plus de 2 s)
        self.open_since = None                # instant du clic main ouverte (None : main pas ouverte)
        self.armed = False                    # souris : la paume est passée au centre de l'image
        self.arm_since = None                 # instant d'entrée dans la zone d'armement
        self.help_until = -1e9                # « iris aide » : affichée jusqu'à cet instant
        self.calendar_until = -1e9            # « iris calendrier » : ouvert jusqu'à cet instant
        self.timer_running = False            # mis à jour par les rappels (même fil) : « iris timer » l'annule
        self.clock_until = -1e9               # « iris heure / date » : pastille de l'heure jusqu'à cet instant
        self.translating = False              # « iris traducteur » : sous-titres du son du PC (#14)
        self.quota_shown = False              # « iris quota » : quota Claude affiché en permanence (repris au démarrage)
        self.repeat_until = -1e9              # « iris skip / back » : « skip » / « back » seuls, sans « iris »
        self.repeat_acts = {}                 # mot répétable -> (actions, libellé affiché)
        self.type_erase_until = -1e9          # « iris annule » efface la dernière dictée jusque-là (14/11)
        self.asking = False                   # « iris question » : la question est en cours d'enregistrement
        self.ask_t0 = -1e9
        # voix
        self.listen_until = -1e9
        self.bypass_until = -1e9         # « iris bypass » : mots acceptés même mal dits jusqu'à cet instant
        self.cand_until = -1e9           # « iris candidature » : mots de CVGEN sans « iris » jusqu'à cet instant
        self.focus_until = -1e9          # mode focus : commandes sans « iris » jusqu'à cet instant
        self.voice_scroll_until = -1e9
        self.voice_scroll_armed = False       # la main est passée dans la bande du centre
        self.voice_scroll_y0 = 0.5            # centre du défilement ; à la tête, il suit au-delà de la butée
        self.voice_scroll_dy = 0.0            # écart au centre, borné (affiché dans la jauge)
        self.voice_scroll_since = None        # entrée dans cette bande
        self._scroll_acc = 0.0
        self.last_word = None       # (mot, t, accepté ?)
        self.top_shown = False      # réponse / rappel / liste affichés en haut : écrit par la boucle principale
        self.reminder_shown = False # un rappel affiché (pour « plus tard » sans « iris ») : écrit par la boucle
        self.front_exe = ""         # dernière appli à toi au premier plan (fenêtres d'Iris exclues), via front_app
        # dictée Claude dans VS Code : micro allumé, puis texte dicté en attente de « envoie » / « annule »
        self.dictating = False
        self.dictation_t0 = -1e9
        self.confirm_until = -1e9
        self.confirm_kind = "claude"          # « claude » (VS Code) ou « type » (texte écrit à l'endroit actif)
        # « iris type » : la dictée est en cours d'enregistrement (texte écrit à l'endroit du curseur)
        self.typing = False
        self.type_t0 = -1e9
        self.opening = False                  # « iris ouvre » : le nom de l'appli est en cours d'enregistrement
        self.open_t0 = -1e9
        self.open_kind = "open"               # « open » (iris ouvre) ou « close » (iris ferme)
        # pour l'affichage
        self.still_for = 0.0
        self.zone_progress = 0.0
        self.zone_side = None
        self.palm = None

    # --- modes -------------------------------------------------------------
    def _reset(self):
        self.still.reset()
        self.zone.reset()
        self.scroll.reset()
        self.scroll_progress, self.scroll_side = 0.0, None
        self.menu.close()
        self.fx.reset()
        self.fy.reset()
        self.prev_palm = None
        self.bubble = None
        self.need_move = False
        self.travel = 0.0
        self.still_for = 0.0
        self.zone_progress = 0.0
        self.zone_side = None

    def set_mouse(self, on, t, acts):
        """Allume / éteint la souris à la main, sans toucher au mode en cours."""
        if on == self.mouse:
            return
        if not on:
            acts.append(("release_all",))
            self.pressing = False
            self.open_since = None
        self.mouse = on
        self.head.reset()                     # la tête de face à l'allumage = centre
        self._reset()
        acts.append(("mouse", on))
        if on:
            self._center(acts)                # la souris commence toujours au centre
        self.feed.append(("SOURIS " + ("ON" if on else "OFF"), t))

    def set_pointer(self, pointer, t, acts):
        """Main ou tête pour la souris (voix « iris main / tête », bouton de l'accueil)."""
        if pointer not in ("main", "tete") or pointer == self.pointer:
            return
        self.pointer = pointer
        self.head.reset()
        acts.append(("release_all",))
        acts.append(("pointer", pointer))
        if self.mouse:
            self._center(acts)                # on repart du centre avec le nouveau pointeur
        self.feed.append((f"POINTEUR {pointer.upper()}", t))

    def set_pointer_toggle(self, t):
        """Bouton de l'accueil : bascule main <-> tête ; renvoie les actions."""
        acts = []
        self.set_pointer("main" if self.pointer == "tete" else "tete", t, acts)
        self.last_gesture = ("SOURIS A LA " + ("TETE" if self.pointer == "tete" else "MAIN"), t)
        return acts

    def step_head(self, lms, t, matrix=None):
        """Pointeur « tête » : lms = points (x, y) du visage (ou None), matrix = orientation donnée par
        MediaPipe (4x4, ou None). Seule la souris suit la tête."""
        acts = []
        if self.mode == Mode.DISABLED:
            return acts
        point = self.head.point(lms, matrix, t) if lms is not None else None
        if point is None:
            return self._no_hand(t, acts)
        if (self.mouse and self.last_seen is not None
                and t - self.last_seen >= self.cfg.recenter_absent_s):
            self.head.reset()
            self._center(acts)                # visage revenu : on repart du centre
            point = self.head.point(lms, matrix, t)
        self.last_seen = t
        self.released = False
        if self.scrolling(t):                 # défilement : hauteur non bornée (tête baissée à fond)
            point = (point[0], getattr(self.head, "raw_y", point[1]))
        palm = (self.fx(point[0], t), self.fy(point[1], t))
        self.palm = palm
        self.still_for = self.still.update(palm, t)
        if self.still_for == 0.0:
            self.need_move = False
        if t < self.voice_scroll_until:
            self._voice_scroll(palm, t, acts)
        elif self.mouse:
            self._mouse(palm, t, acts)
        self.prev_palm, self.prev_t = palm, t
        return acts

    def set_mode(self, mode, t, acts, why="", auto=False):
        """why : cause, notée dans le journal ; auto : changement suivi de l'appli devant (sans son)."""
        if mode == Mode.MOUSE:                # ancien appel (enregistrements, tests) : allume la souris
            self.set_mouse(True, t, acts)
            return
        if mode == Mode.DISABLED:
            self.set_mouse(False, t, acts)    # pause : plus rien ne bouge
        if mode == self.mode:
            return
        self.mode = mode
        self.mode_since = t
        self.mode_why = why
        self.mode_auto = auto
        self.chrome_seen = False
        self._reset()
        acts.append(("mode", mode))
        self.feed.append((f"MODE {mode}", t))

    def _center(self, acts):
        sx, sy, sw, sh = self.screen
        self.cursor = (sx + sw // 2, sy + sh // 2)
        self._cursor_f = [float(self.cursor[0]), float(self.cursor[1])]
        self.cursor_hist.clear()
        self.prev_palm = None
        self.armed = False                    # le curseur attend que la paume revienne au centre de l'image
        self.arm_since = None
        self.fx.reset()
        self.fy.reset()
        acts.append(("move", *self.cursor))

    def disable(self, t):
        self.dragging = False
        acts = [("release_all", "force")]
        self.set_mode(Mode.DISABLED, t, acts)
        return acts

    def enable(self, t):
        acts = []
        self.set_mode(Mode.NEUTRAL, t, acts)
        return acts

    def front_app(self, exe, t):
        """Appelé par la boucle avec le programme au premier plan (« chrome.exe »…). Le mode Chrome suit Chrome :
        devant -> mode Chrome (depuis le neutre ; la lecture, choisie à la voix, reste) ; une autre appli devant
        -> neutre. Les fenêtres d'Iris et « rien devant » ne changent rien."""
        acts = []
        if not exe or exe in IRIS_EXES:
            return acts
        self.front_exe = exe
        if self.mode == Mode.DISABLED:
            return acts
        if exe == "chrome.exe":
            if self.mode == Mode.NEUTRAL:
                self.set_mode(Mode.CHROME, t, acts, why="Chrome devant", auto=True)
            if self.mode == Mode.CHROME:
                self.chrome_seen = True
        elif self.mode == Mode.CHROME and (self.chrome_seen or t - self.mode_since > CHROME_GRACE_S):
            found = self.chrome_seen
            self.set_mode(Mode.NEUTRAL, t, acts, why=f"{exe} devant", auto=found)
            self.last_gesture = ("MODE CHROME QUITTE" if found else "CHROME INTROUVABLE", t)
        return acts

    def _in_vscode(self):
        """VS Code est l'appli devant (hors mode Chrome) : suivant / précédent y sont des onglets."""
        return self.front_exe == "code.exe" and self.mode != Mode.CHROME

    def chrome_front(self, front, t):
        """Ancien appel (tests) : Chrome devant ou une autre appli."""
        return self.front_app("chrome.exe" if front else "autre.exe", t)
