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
import math
from collections import deque

from .filters import OneEuro
from .gestures import RadialMenu, ScrollDetector, StillnessDetector, ZoneDetector
from .hand import compute_features
from .head import HeadPointer
from .poses import UNSURE, PoseVoter, classify, flexion


class Mode:
    DISABLED = "DESACTIVE"
    NEUTRAL = "NEUTRE"    # par défaut : la main ne déclenche rien, seule la voix agit
    READING = "LECTURE"
    MOUSE = "SOURIS"      # n'est plus un mode : un outil qui s'ajoute au mode en cours (voir Core.mouse)
    CHROME = "CHROME"     # « iris chrome » : commandes de navigation à la voix ; quitté dès que Chrome n'est plus devant
    IDLE = READING  # compatibilité : l'ancien « repos » est désormais la lecture


MENU_LABELS = {"left": "CLIC GAUCHE", "right": "CLIC DROIT", "up": "DOUBLE CLIC", "down": "SOURIS ETEINTE"}
WAKE_WORD = "iris"
VOICE_HOTKEYS = {"entrée": ["enter"], "espace": ["space"], "space": ["space"], "copie": ["ctrl", "c"], "colle": ["ctrl", "v"],
                 "skip": ["right"], "back": ["left"],   # flèches : ±10 s sur YouTube
                 # texte et fenêtres (check-up du 13/11) ; en mode Chrome, « agrandis / réduis » restent le zoom
                 "sélection": ["ctrl", "a"], "coupe": ["ctrl", "x"], "efface": ["ctrl", "backspace"],
                 "réduis": ["win", "down"],
                 "gauche": ["win", "left"], "droite": ["win", "right"]}
from .calendar_view import WORDS as CAL_WORDS

# mode CHROME : mot dit (après « iris ») -> touches envoyées à Chrome, seulement s'il est au premier plan
CHROME_KEYS = {"retour": ["alt", "left"], "avance": ["alt", "right"],
               "suivant": ["ctrl", "tab"], "précédent": ["ctrl", "shift", "tab"],
               "onglet": ["ctrl", "t"], "ferme": ["ctrl", "w"], "rouvre": ["ctrl", "shift", "t"],
               "recharge": ["f5"], "favori": ["ctrl", "d"], "haut": ["home"], "bas": ["end"],
               "descends": ["pagedown"], "monte": ["pageup"],
               "agrandis": ["ctrl", "plus"], "réduis": ["ctrl", "minus"],
               "recherche": ["ctrl", "l"]}   # recherche : barre d'adresse puis dictée (comme « type »)
CHROME_LABELS = {"retour": "PAGE PRECEDENTE", "avance": "PAGE SUIVANTE", "suivant": "ONGLET SUIVANT",
                 "précédent": "ONGLET PRECEDENT", "onglet": "NOUVEL ONGLET", "ferme": "ONGLET FERME",
                 "rouvre": "ONGLET ROUVERT", "recharge": "PAGE RECHARGEE", "favori": "FAVORI",
                 "haut": "HAUT DE PAGE", "bas": "BAS DE PAGE", "descends": "PAGE BAS", "monte": "PAGE HAUT",
                 "agrandis": "ZOOM +", "réduis": "ZOOM -", "recherche": "RECHERCHE : parle"}
CHROME_GRACE_S = 5.0      # « iris chrome » : le temps que Chrome s'ouvre avant de juger qu'il n'est pas devant

ALIASES = {"envoyé": "envoie",   # « envoyé » vient plus naturellement (demande de l'utilisateur, 12/11)
           # français et anglais font la même chose (12/11) ; « deafen » n'existe pas dans le modèle : « défun »
           "muet": "mute", "sourdine": "défun",
           "ok": "merci", "okay": "merci"}   # « iris ok » = « iris merci » : retire l affichage du haut (13/11)
CAL_IDLE_S = 60.0         # calendrier ouvert sans commande : fermé
REPEATABLE = ("skip", "back", "efface")   # après « iris skip / back / efface », redits seuls sans « iris »
# mot dit -> ce qui se passe (affiché en grand, et dans le panneau d'aide)
VOICE_LABELS = {"clic": "CLIC GAUCHE", "double": "DOUBLE CLIC", "menu": "CLIC DROIT",
                "glisse": "GLISSER (bouton tenu)", "lâche": "LACHER", "entrée": "TOUCHE ENTREE",
                "espace": "TOUCHE ESPACE", "space": "TOUCHE ESPACE",
                "annule": "TOUCHE ECHAP", "copie": "COPIER (Ctrl+C)", "colle": "COLLER (Ctrl+V)",
                "claude": "MICRO CLAUDE : parle",
                "type": "DICTEE : parle",
                "tab": "FENETRE SUIVANTE (Alt+Tab)", "discord": "DISCORD", "chrome": "CHROME", "studio": "VS CODE", "accueil": "ACCUEIL MOTIONZERO",
                "mute": "DISCORD COUPE", "démute": "DISCORD RALLUME", "défun": "DISCORD SOURDINE", "souris": "SOURIS",
                "lecture": "LECTURE", "message": "MESSAGE DISCORD : salon puis texte",
                "salon": "SALON VOCAL : dis son nom", "silence": "LECTURE DISCORD COUPEE",
                "lis": "LECTURE DISCORD ACTIVE",
                "skip": "AVANCE (fleche droite)", "back": "RECULE (fleche gauche)",
                "sélection": "TOUT SELECTIONNE (Ctrl+A)", "coupe": "COUPER (Ctrl+X)", "efface": "MOT EFFACE",
"réduis": "FENETRE REDUITE",
                "gauche": "FENETRE A GAUCHE", "droite": "FENETRE A DROITE",
                "rappel": "RAPPEL : dis quand et quoi", "merci": "RAPPEL VALIDE",
                "plus tard": "RAPPEL DANS 10 MIN", "volume": "VOLUME : dis le niveau", "heure": "HEURE", "date": "DATE"}
# « iris ouvre / ferme / message / salon » : ce qui est enregistré puis transcrit par Whisper
OPEN_STOP = {"open": "open_stop", "close": "close_stop", "message": "message_stop", "salon": "salon_stop",
             "rappel": "rappel_stop", "timer": "timer_stop",
             "volume": "volume_stop"}
OPEN_WAIT = {"open": "OUVRE : je cherche l'appli…", "close": "FERME : je cherche l'appli…",
             "message": "MESSAGE : envoi au bot…", "salon": "SALON : je cherche…",
             "rappel": "RAPPEL : Haiku reflechit…", "timer": "TIMER : je lis la duree…",
             "volume": "VOLUME : je regle…"}


# « iris + mot » sans état : une action, et un libellé (None = celui de VOICE_LABELS)
SIMPLE_ACTIONS = {"plein écran": (("window", "max"), "PLEIN ECRAN"),   # partout, Chrome compris
                  "agrandis": (("window", "max"), "PLEIN ECRAN"),      # hors mode Chrome (là : zoom)
                  "envoie": (("hotkey", ["enter"]), "TOUCHE ENTREE"),   # Entrée dans la fenêtre active
                  "annule": (("annule",), "ANNULE"),   # vide le message de Claude si VS Code est devant, sinon Échap
                  "tab": (("alt_tab",), None),
                  "réveil": (("wake",), "ECRAN RALLUME"), "wake": (("wake",), "ECRAN RALLUME"),
                  "chronomètre": (("chrono",), "CHRONOMETRE"),
                  "plus tard": (("rappel_tard",), None),
                  "activation": (("bot_activate",), "BOT VOCAL : ACTIVATION"),   # lance le bot, charge Whisper
                  "viens": (("bot_join",), "IRIS : J'ARRIVE EN VOCAL"),
                  "pars": (("bot_leave",), "IRIS QUITTE LE VOCAL"),
                  "silence": (("discord_hush",), None), "lis": (("discord_read",), None),
                  "mute": (("discord_mute",), None), "démute": (("discord_unmute",), None),
                  "défun": (("discord_deafen",), None)}
# « iris + mot » avec de l'état : mot -> méthode Core._cmd_<nom>
COMMANDS = {"clic": "click", "double": "click", "menu": "click", "glisse": "drag", "lâche": "release",
            "défile": "scroll", "claude": "claude", "souris": "mouse", "question": "question", "ouvre": "open",
            "type": "type", "ferme": "close", "timer": "timer", "calendrier": "calendar",
            "heure": "clock", "date": "clock", "merci": "thanks",
            "message": "listen", "salon": "listen", "rappel": "listen", "volume": "listen",
            "tête": "pointer", "main": "pointer", "centre": "center", "lecture": "reading",
            "discord": "app", "chrome": "app", "studio": "app", "accueil": "app", "pause": "pause"}


class Core:
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
        self.calendar_until = -1e9            # « iris calendrier » : ouvert jusqu'à cet instant
        self.timer_running = False            # mis à jour par les rappels (même fil) : « iris timer » l'annule
        self.clock_until = -1e9               # « iris heure / date » : pastille de l'heure jusqu'à cet instant
        self.repeat_until = -1e9              # « iris skip / back » : « skip » / « back » seuls, sans « iris »
        self.asking = False                   # « iris question » : la question est en cours d'enregistrement
        self.ask_t0 = -1e9
        # voix
        self.listen_until = -1e9
        self.voice_scroll_until = -1e9
        self.voice_scroll_armed = False       # la main est passée dans la bande du centre
        self.voice_scroll_y0 = 0.5            # centre du défilement ; à la tête, il suit au-delà de la butée
        self.voice_scroll_dy = 0.0            # écart au centre, borné (affiché dans la jauge)
        self.voice_scroll_since = None        # entrée dans cette bande
        self._scroll_acc = 0.0
        self.last_word = None       # (mot, t, accepté ?)
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

    def set_mode(self, mode, t, acts):
        if mode == Mode.MOUSE:                # ancien appel (enregistrements, tests) : allume la souris
            self.set_mouse(True, t, acts)
            return
        if mode == Mode.DISABLED:
            self.set_mouse(False, t, acts)    # pause : plus rien ne bouge
        if mode == self.mode:
            return
        self.mode = mode
        self.mode_since = t
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
        acts = [("release_all",)]
        self.set_mode(Mode.DISABLED, t, acts)
        return acts

    def enable(self, t):
        acts = []
        self.set_mode(Mode.NEUTRAL, t, acts)
        return acts

    # --- boucle ------------------------------------------------------------
    def step(self, pts, t, world=None):
        """world : les 21 points 3D « monde » de la même main (pour reconnaître l'index pointé)."""
        acts = []
        if self.mode == Mode.DISABLED:
            return acts
        if pts is None:
            return self._no_hand(t, acts)
        if (self.mouse and self.last_seen is not None
                and t - self.last_seen >= self.cfg.recenter_absent_s):
            self._center(acts)                # la main revient : le curseur repart du centre
        self.last_seen = t
        self.released = False
        self.features = compute_features(pts, self.cfg)
        palm = (self.fx(self.features.palm[0], t), self.fy(self.features.palm[1], t))
        self.palm = palm
        self.still_for = self.still.update(palm, t)
        if self.still_for == 0.0:
            self.need_move = False
        if t < self.voice_scroll_until:
            self._voice_scroll(palm, t, acts)
            self.prev_palm, self.prev_t = palm, t
            return acts
        if self.mouse:                        # la souris passe avant les gestes du mode
            self._mouse(palm, t, acts)
            if self.cfg.hand_click_enabled:
                self._index_click(world, t, acts)
        elif self.mode == Mode.READING:
            self._reading(palm, t, acts)
        self.prev_palm, self.prev_t = palm, t
        return acts

    def _index_click(self, world, t, acts):
        """Clic par la main : main fermée sans serrer = on vise ; on rouvre la main, détendue -> clic gauche
        simple. Gardée ouverte plus de 2 s -> le bouton s'enfonce et reste appuyé (glisser-déposer) jusqu'à
        ce qu'on referme la main. Le curseur n'est jamais déplacé par le clic. Chaque changement exige
        3 images de suite (~0,15 s) ; rien ne s'arme si la main revient déjà ouverte."""
        c = self.cfg
        if self.pose_cents is None or world is None:
            return
        raw = classify(flexion(world), self.pose_cents)[0]
        self.point_frames = self.point_frames + 1 if raw == c.click_pose else 0
        self.closed_frames = self.closed_frames + 1 if raw == "closed" else 0
        stable = self.pose_voter.update(raw)
        if self.open_since is None and stable in ("closed", "point"):
            self.pose_firm = stable
        if self.open_since is not None:                       # main ouverte après un clic
            if self.closed_frames >= c.index_click_frames:     # refermée : fin (bouton relâché s'il l'était)
                if self.pressing:
                    acts.append(("release", "mouse", "left"))
                    self.last_gesture = ("CLIC RELACHE", t)
                self.pressing = False
                self.open_since = None
                self.pose_firm = "closed"
            elif not self.pressing and t - self.open_since >= c.hold_after_s:
                acts.append(("press", "mouse", "left"))       # gardée ouverte : bouton maintenu
                self.pressing = True
                self.last_gesture = ("CLIC MAINTENU", t)
        elif (self.point_frames >= c.index_click_frames and self.pose_firm == "closed"
                and t - self.last_click_t >= c.index_click_recovery_s):
            acts.append(("click", "left"))
            self.last_click_t = t
            self.open_since = t
            self.pose_firm = c.click_pose
            self.last_gesture = ("CLIC GAUCHE (main ouverte)", t)

    def _no_hand(self, t, acts):
        self.features = None
        self.palm = None
        self.pose_voter.reset()
        self.pose_firm = None                 # main revenue déjà ouverte : pas d'appui
        self.point_frames = 0
        self.closed_frames = 0
        self.pressing = False                 # le bouton est relâché par release_all (main absente)
        self.open_since = None
        if self.last_seen is None:
            return acts
        gone = t - self.last_seen
        if (self.pointer != "tete" and self.voice_scroll_armed and self.scrolling(t)
                and gone >= self.cfg.recenter_absent_s):
            self._end_scroll(t)               # main baissée hors de l'image : fin du défilement
        if not self.released and gone >= self.cfg.release_absent_s:
            acts.append(("release_all",))
            self.released = True
        # Mesuré le 10/11 : entré à la voix main baissée, on ressortait du mode souris 30 ms après.
        # La main absente relâche tout (ci-dessus) mais ne change plus de mode, sauf réglage explicite.
        if self.mouse and self.cfg.absent_mouse_s > 0 and gone >= self.cfg.absent_mouse_s:
            self.set_mouse(False, t, acts)
        # main retirée = « embrayage » : on la repose ailleurs, le curseur ne saute pas
        self.still.reset()
        self.zone.reset()
        self.scroll.reset()
        self.menu.close()
        self.fx.reset()
        self.fy.reset()
        self.prev_palm = None
        self.bubble = None
        self.still_for = 0.0
        self.zone_progress = 0.0
        self.scroll_progress, self.scroll_side = 0.0, None
        return acts

    # --- lecture -----------------------------------------------------------
    def _reading(self, palm, t, acts):
        c = self.cfg
        event, self.zone_progress, self.zone_side = self.zone.update(palm[0], t)
        if event:
            acts.append(("key", c.key_next if event == "next" else c.key_prev))
            self.last_gesture = ("PAGE SUIVANTE" if event == "next" else "PAGE PRECEDENTE", t)
            self.bubble = None
            return
        in_center = c.page_rearm_lo <= palm[0] <= c.page_rearm_hi
        # défilement : en haut / en bas, hors des bandes de page
        notches, self.scroll_progress, self.scroll_side = self.scroll.update(
            palm[1], t, allowed=self.zone_side is None and c.page_band_left < palm[0] < c.page_band_right)
        if notches:
            acts.append(("scroll", notches * c.scroll_notch))
            self.last_gesture = ("DEFILE " + ("HAUT" if notches > 0 else "BAS"), t)
        if self.scroll_side is not None:
            self.bubble = None
            return
        in_center = in_center and c.scroll_band_top < palm[1] < c.scroll_band_bottom
        if self.bubble is None:
            if (c.mouse_bubble and in_center and not self.need_move
                    and self.still_for >= c.mouse_enter_still_s):
                self.bubble = (t, palm[0], palm[1])
            return
        t0, x0, y0 = self.bubble
        dy = palm[1] - y0
        dist = math.hypot(palm[0] - x0, dy)
        if dy <= -c.bubble_confirm_dist and abs(palm[0] - x0) < abs(dy):
            self.last_gesture = ("SOURIS", t)
            self.set_mouse(True, t, acts)
        elif dist >= c.bubble_cancel_dist or t - t0 >= c.bubble_timeout_s:
            self.bubble = None
            self.need_move = True

    # --- souris ------------------------------------------------------------
    def _gain(self, speed):
        c = self.cfg
        k = min(max((speed - c.gain_speed_lo) / (c.gain_speed_hi - c.gain_speed_lo), 0.0), 1.0)
        lo, hi = (c.head_gain_min, c.head_gain_max) if self.pointer == "tete" else (c.gain_min, c.gain_max)
        return lo + (hi - lo) * k

    def _mouse(self, palm, t, acts):
        c = self.cfg
        if self.menu.is_open:
            choice = self.menu.update(palm, t)
            if choice in ("left", "right"):
                acts.append(("click", choice))
            elif choice == "up":
                acts += [("click", "left"), ("click", "left")]
            elif choice == "down":
                self.last_gesture = (MENU_LABELS["down"], t)
                self.set_mouse(False, t, acts)    # le mode en cours (Chrome, lecture…) reste
                return
            if choice and choice != "cancel":
                self.last_gesture = (MENU_LABELS[choice], t)
                self.last_click_t = t
            if choice:
                self.travel = 0.0
                self.still.reset()
            return

        if not self.armed:
            # course égale dans chaque direction : on part du centre de l'image (issue #15)
            ax, ay = c.arm_center
            if math.hypot(palm[0] - ax, palm[1] - ay) > c.arm_radius:
                self.arm_since = None
                return
            if self.arm_since is None:
                self.arm_since = t
            if t - self.arm_since < c.arm_hold_s:
                return
            self.armed = True                 # prev_palm = cette paume : aucun saut au départ
            self.last_gesture = ("SOURIS ARMEE", t)
            return

        if self.prev_palm is not None and t >= self.freeze_until:
            dt = max(t - self.prev_t, 1e-3)
            dx, dy = palm[0] - self.prev_palm[0], palm[1] - self.prev_palm[1]
            gain = self._gain(math.hypot(dx, dy) / dt)
            sx, sy, sw, sh = self.screen
            nx = min(max(self._cursor_f[0] + dx * sw * gain, sx), sx + sw - 1)
            ny = min(max(self._cursor_f[1] + dy * sw * gain, sy), sy + sh - 1)
            self.travel += math.hypot(nx - self._cursor_f[0], ny - self._cursor_f[1])
            self._cursor_f = [nx, ny]
            new = (int(round(nx)), int(round(ny)))
            if math.hypot(new[0] - self.cursor[0], new[1] - self.cursor[1]) >= c.deadzone_px:
                self.cursor = new
                acts.append(("move", *new))

        self.cursor_hist.append((t, self.cursor))
        if (c.click_menu_on_still and self.still_for >= c.dwell_menu_s and self.travel >= c.rearm_px
                and t - self.last_click_t >= c.click_recovery_s):
            self.menu.open(palm, t)

    # --- voix ----------------------------------------------------------------
    def listening(self, t):
        """L'écoute est ouverte après « iris », ou tant que la bulle / le menu (main immobile) sont affichés."""
        # (après une dictée, envoie / annule / claude sont traités à part : l'écoute n'est pas ouverte
        # pour autant, sinon n'importe quel mot seul serait exécuté pendant 30 s)
        return self.mode != Mode.DISABLED and (t < self.listen_until or self.bubble is not None
                                               or self.menu.is_open)

    def voice(self, word, t, t_start=None):
        """Un mot reconnu (déjà filtré : dit seul). Renvoie les actions.
        Ordre des étapes = ordre de priorité : chacune traite le mot (et renvoie les actions) ou passe (None)."""
        word = ALIASES.get(word, word)
        if self.dictating or self.asking or self.typing or self.opening:
            return []  # dictée ou question en cours : tes mots sont du texte, pas des commandes
        acts = []
        for step in (self._v_confirm, self._v_calendar, self._v_stop, self._v_without_iris, self._v_wake, self._v_resume):
            done = step(word, t, t_start, acts)
            if done is not None:
                return done
        if not self.listening(t):
            self.last_word = (word, t, False)  # entendu mais écoute fermée : ignoré
            self.last_gesture = (f'"{word}" ignore : dis IRIS avant', t)
            return acts
        return self._v_command(word, t, acts)

    # --- étapes de voice() : chacune renvoie la liste d'actions si elle traite le mot, sinon None ---
    def _v_confirm(self, word, t, t_start, acts):
        """Juste après « iris type / claude / rappel » : envoie / annule (et claude) marchent sans « iris »."""
        if not self.confirming(t):
            return None
        if self.confirm_kind == "type" and word != WAKE_WORD:
            # tout autre mot : le texte reste tel quel et le mot est traité normalement
            self.confirm_until = -1e9
            if word in ("envoie", "annule"):
                self.last_word = (word, t, True)
                self.last_gesture = ("TEXTE ENVOYE" if word == "envoie" else "TEXTE EFFACE", t)
                return [("type_send",)] if word == "envoie" else [("type_erase",)]
        elif self.confirm_kind == "claude" and word in ("envoie", "annule", "claude"):
            # aucun verrou : toutes les autres commandes « iris + … » restent utilisables
            return self._confirm(word, t)
        elif self.confirm_kind == "rappel" and word in ("envoie", "annule"):
            self.confirm_until = -1e9
            self.last_word = (word, t, True)
            return [("rappel_ok",)] if word == "envoie" else [("rappel_non",)]
        return None

    def _v_calendar(self, word, t, t_start, acts):
        """Calendrier ouvert : ses mots marchent sans « iris » ; ferme / merci / ok / stop le ferment."""
        if t < self.calendar_until:
            if word in CAL_WORDS:
                self.calendar_until = t + CAL_IDLE_S
                self.last_word = (word, t, True)
                self.listen_until = -1e9
                return [("cal", word)]
            if word in ("ferme", "merci"):
                self.calendar_until = -1e9
                self.last_word = (word, t, True)
                self.listen_until = -1e9
                self.last_gesture = ("CALENDRIER FERME", t)
                return [("cal_close",)]
            if word == "stop":
                self.calendar_until = -1e9
                acts.append(("cal_close",))       # puis le « stop » habituel
        elif word in CAL_WORDS and not (self.mode == Mode.CHROME and word in CHROME_KEYS):
            self.last_word = (word, t, False)     # calendrier fermé : ces mots ne font rien, sans bruit
            return acts
        return None

    def _v_stop(self, word, t, t_start, acts):
        """« stop » : toujours écouté, prioritaire. « lâche » : un bouton tenu doit toujours pouvoir être relâché."""
        if word == "stop":
            acts += [("release_all",), ("alarm_stop",)]   # une alarme qui sonne se tait aussi
            self._quiet()
            scrolling = t < self.voice_scroll_until
            self.voice_scroll_until = self.listen_until = -1e9
            if scrolling:                     # « stop » pendant le défilement : fin du défilement seulement
                self._end_scroll(t)
            elif self.mouse:
                self.set_mouse(False, t, acts)  # souris allumée : « stop » l'éteint seulement, le mode reste
            elif self.mode in (Mode.READING, Mode.CHROME):
                self.set_mode(Mode.NEUTRAL, t, acts)
            self.last_gesture = ("STOP", t)
            self.last_word = (word, t, True)
            return acts
        if word == "lâche" and self.dragging:
            self.dragging = False
            self.last_word = (word, t, True)
            self.last_gesture = (VOICE_LABELS["lâche"], t)
            return [("release", "mouse", "left")]
        return None

    def _heard_alone(self, word, t, label):
        """Mot accepté sans « iris » : l'écoute se ferme et le curseur est libéré."""
        self.last_word = (word, t, True)
        self.listen_until = -1e9
        self.freeze_until = -1e9
        self.last_gesture = (label, t)

    def _v_without_iris(self, word, t, t_start, acts):
        """Mots acceptés sans « iris » selon le contexte : répétition (skip, efface…), mode Chrome, souris allumée."""
        if t < self.repeat_until:
            if word in REPEATABLE:            # « skip, skip, skip » : chaque mot relance la fenêtre de 2 s
                self.repeat_until = t + self.cfg.repeat_s
                self.last_word = (word, t, True)
                self.last_gesture = (VOICE_LABELS[word], t)
                return [("hotkey", VOICE_HOTKEYS[word])]
            self.repeat_until = -1e9          # autre mot : fin de la répétition, comportement habituel
        chrome = self.mode == Mode.CHROME
        if chrome and word in ("skip", "back", "espace", "space"):
            # mode Chrome : vidéo (±10 s, pause) sans « iris » (demande de l'utilisateur, 12/11)
            self._heard_alone(word, t, VOICE_LABELS[word])
            return [("hotkey", VOICE_HOTKEYS[word])]
        if (chrome and word in ("clic", "double")) or (self.mouse and word in ("clic", "double", "menu")):
            # mode Chrome ou souris allumée : clic, double clic (et clic droit en souris) sans « iris » (12/11)
            # « iris clic » : on vise le début de « iris » ; « clic » seul : le début du mot
            ref = self.wake_t if self.listening(t) else (t_start if t_start is not None else t)
            self._heard_alone(word, t, VOICE_LABELS[word])
            self._aim(ref, acts)
            self._click(word, t, acts)
            return acts
        if chrome and word in CHROME_KEYS:
            # ses mots ne sont écoutés qu'en mode Chrome (voir voice.GRAMMARS), donc jamais pris ailleurs
            self._heard_alone(word, t, CHROME_LABELS[word])
            acts.append(("chrome_keys", CHROME_KEYS[word]))
            if word == "recherche":
                self.typing = True
                self.type_t0 = t
                acts.append(("type_start",))
            return acts
        return None

    def _v_wake(self, word, t, t_start, acts):
        if word != WAKE_WORD:
            return None
        self.wake_t = t_start if t_start is not None else t
        self.listen_until = t + self.cfg.listen_s
        if self.mode == Mode.DISABLED:
            # en pause, « iris » seul ne réveille plus (il était dit dans la conversation) : il faut « iris reprise »
            self.last_word = (word, t, True)
            self.last_gesture = ("PAUSE : dis IRIS REPRISE", t)
            return acts
        self.last_word = (word, t, True)
        self.last_gesture = ("IRIS : ECOUTE OUVERTE", t)
        return acts

    def _v_resume(self, word, t, t_start, acts):
        """En pause : seul « iris reprise » réactive ; tout autre mot est ignoré."""
        if self.mode != Mode.DISABLED:
            return None
        if word == "reprise" and t < self.listen_until:
            self.listen_until = -1e9
            self.set_mode(Mode.NEUTRAL, t, acts)
            self.last_word = (word, t, True)
            self.last_gesture = ("REPRISE", t)
        else:
            self.last_word = (word, t, False)
        return acts

    def _v_command(self, word, t, acts):
        """« iris » + un mot : une seule commande par « iris » (avant, la fenêtre restait ouverte 8 s et un mot de
        la conversation qui suivait — « colle », « chrome » — était exécuté)."""
        self.last_word = (word, t, True)
        self.freeze_until = -1e9              # commande reçue : le curseur est libéré après elle
        self.listen_until = -1e9
        if word in CHROME_KEYS and word != "ferme" and word not in VOICE_HOTKEYS and word not in SIMPLE_ACTIONS:
            # hors mode Chrome : « ferme » garde son sens habituel, « agrandis / réduis » gèrent la fenêtre
            self.last_word = (word, t, False)
            self.last_gesture = (f"{word.upper()} : seulement en mode Chrome", t)
            return acts
        if word != "défile" and self.scrolling(t):
            self._end_scroll(t)               # toute autre commande sort du défilement d'abord
        label = VOICE_LABELS.get(word, word.upper())
        if word in SIMPLE_ACTIONS:
            action, simple_label = SIMPLE_ACTIONS[word]
            acts.append(action)
            label = simple_label or label
        elif word in VOICE_HOTKEYS:
            acts.append(("hotkey", VOICE_HOTKEYS[word]))
            if word in REPEATABLE:
                self.repeat_until = t + self.cfg.repeat_s
        elif word in COMMANDS:
            label = getattr(self, "_cmd_" + COMMANDS[word])(word, t, acts) or label
        self.last_gesture = (label, t)
        return acts

    # --- petites aides des commandes ---
    def _click(self, word, t, acts):
        acts += [("click", "right")] if word == "menu" else [("click", "left")] * (2 if word == "double" else 1)
        self.menu.close()
        self.last_click_t = t
        self.travel = 0.0

    def _quiet(self):
        """Ferme le menu et la bulle de la main (avant une dictée, une écoute, ou sur « stop »)."""
        self.menu.close()
        self.bubble = None

    def _start_open(self, kind, t, acts, label=None):
        """Écoute d'une phrase libre (Whisper) : nom d'appli, durée, message, rappel, volume…"""
        self.opening = True
        self.open_t0 = t
        self.open_kind = kind
        acts.append(("open_start",))
        return label

    # --- commandes « iris + mot » (table COMMANDS) : ajoutent leurs actions, renvoient un libellé ou None ---
    def _cmd_click(self, word, t, acts):
        self._aim(self.wake_t, acts)          # là où l'on visait en disant « iris »
        self._click(word, t, acts)

    def _cmd_drag(self, word, t, acts):
        self._aim(self.wake_t, acts)
        acts.append(("press", "mouse", "left"))
        self.dragging = True

    def _cmd_release(self, word, t, acts):
        acts.append(("release", "mouse", "left"))

    def _cmd_scroll(self, word, t, acts):
        if self.scrolling(t):                 # « iris défile » une 2e fois : on en sort
            self._end_scroll(t)
            return "DEFILEMENT FINI"
        self.voice_scroll_until = math.inf    # actif jusqu'à « iris défile », « stop » ou une autre commande
        self.voice_scroll_armed = False
        self.voice_scroll_since = None
        self._scroll_acc = 0.0
        self._quiet()
        return "DEFILE : amene la main au centre"

    def _cmd_claude(self, word, t, acts):
        self.dictating = True
        self.dictation_t0 = t
        self._quiet()
        acts.append(("vscode_dictation",))

    def _cmd_mouse(self, word, t, acts):
        # allume ou éteint la souris ; le mode en cours (Chrome…) ne change pas
        self.set_mouse(not self.mouse, t, acts)
        return "SOURIS" if self.mouse else "SOURIS ETEINTE"

    def _cmd_question(self, word, t, acts):
        self.asking = True
        self.ask_t0 = t
        acts.append(("ask_start",))
        return "POSE TA QUESTION"

    def _cmd_open(self, word, t, acts):
        return self._start_open("open", t, acts, "OUVRE : dis le nom de l'appli")

    def _cmd_type(self, word, t, acts):
        self.typing = True
        self.type_t0 = t
        self._quiet()
        acts.append(("type_start",))

    def _cmd_close(self, word, t, acts):
        # retire la réponse affichée ET écoute un éventuel nom d'appli à fermer (en mode Chrome, « ferme »
        # ferme l'onglet : pour l'affichage du haut, « merci » / « ok » marchent partout)
        acts.append(("ask_close",))
        return self._start_open("close", t, acts, "FERME : dis le nom de l'appli")

    def _cmd_timer(self, word, t, acts):
        if self.timer_running:
            acts.append(("timer_cancel",))
            return "TIMER ANNULE"
        return self._start_open("timer", t, acts, "TIMER : combien de temps ?")

    def _cmd_calendar(self, word, t, acts):
        self.calendar_until = t + CAL_IDLE_S
        acts.append(("cal_open",))

    def _cmd_clock(self, word, t, acts):
        self.clock_until = t + self.cfg.clock_s

    def _cmd_thanks(self, word, t, acts):
        # « vu » : tout ce qui est affiché en haut disparaît (rappel validé, réponse, liste, heure)
        acts += [("rappel_merci",), ("ask_close",)]
        self.clock_until = -1e9

    def _cmd_listen(self, word, t, acts):
        # message, salon, rappel, volume : la suite est une phrase libre (« iris volume » puis « 40 »…)
        self._quiet()
        self._start_open(word, t, acts)
        if word == "volume":
            acts.append(("volume_show",))     # barre de volume à droite, avec le niveau actuel

    def _cmd_pointer(self, word, t, acts):
        self.set_pointer("tete" if word == "tête" else "main", t, acts)
        return "SOURIS A LA " + ("TETE" if word == "tête" else "MAIN")

    def _cmd_center(self, word, t, acts):
        self.head.reset()                     # tête de face maintenant = centre
        if self.mouse:
            self._center(acts)
        return "CURSEUR AU CENTRE"

    def _cmd_reading(self, word, t, acts):
        self.set_mouse(False, t, acts)        # la main sert aux pages, plus au curseur
        if self.mode != Mode.READING:
            self.set_mode(Mode.READING, t, acts)
        return "LECTURE"

    def _cmd_app(self, word, t, acts):
        acts.append(("open_app", word))
        if word == "chrome":
            self.set_mode(Mode.CHROME, t, acts)
        elif self.mode == Mode.CHROME:
            self.set_mode(Mode.NEUTRAL, t, acts)

    def _cmd_pause(self, word, t, acts):
        acts.append(("release_all",))
        self.set_mode(Mode.DISABLED, t, acts)
        self.listen_until = -1e9
        return "PAUSE (dis IRIS REPRISE pour reprendre)"

    def scroll_gauge(self, t):
        """Jauge du défilement vocal : (hauteur de la main 0..1, armé ?, demi-bande d'armement, demi-zone neutre),
        ou None hors défilement. Comme la main fantôme de la souris, montre où l'on est par rapport au centre."""
        if t >= self.voice_scroll_until:
            return None
        arm, dead, _, span = self._scroll_params()
        if self.palm is None:
            return (None, self.voice_scroll_armed, arm, dead)
        if not self.voice_scroll_armed:
            dy = self.palm[1] - 0.5
        else:
            dy = self.voice_scroll_dy
        if span < 0.5:                        # tête : la jauge entière = la course bornée (±span)
            k = 0.4 / span
            return (min(max(0.5 + dy * k, 0.0), 1.0), self.voice_scroll_armed, arm * k, dead * k)
        return (0.5 + dy, self.voice_scroll_armed, arm, dead)

    def ghost(self):
        """Main fantôme (souris pas encore armée) : où est la paume, à l'écran, par rapport au centre visé.
        Renvoie (x, y, rayon de la zone du centre) en pixels, ou None. L'image entière = l'écran entier.
        « défile » pas encore armé (main) : (x, y, demi-bande, y du centre) — seule la hauteur compte."""
        sx, sy, sw, sh = self.screen
        if (self.palm is not None and self.pointer != "tete" and self.voice_scroll_until > (self.prev_t or 0.0)
                and not self.voice_scroll_armed):
            arm = self._scroll_params()[0]
            cy = sy + sh / 2
            x = min(max(sx + self.palm[0] * sw, sx), sx + sw - 1)
            y = min(max(cy + (self.palm[1] - 0.5) * sh, sy), sy + sh - 1)
            return (x, y, arm * sh, cy)
        if not self.mouse or self.armed or self.palm is None or self.voice_scroll_until > (self.prev_t or 0.0):
            return None
        sx, sy, sw, sh = self.screen
        ax, ay = self.cfg.arm_center
        cx, cy = sx + sw / 2, sy + sh / 2
        x = min(max(cx + (self.palm[0] - ax) * sw, sx), sx + sw - 1)
        y = min(max(cy + (self.palm[1] - ay) * sh, sy), sy + sh - 1)
        return (x, y, self.cfg.arm_radius * sw)

    def chrome_front(self, front, t):
        """Appelé par la boucle : Chrome est-il au premier plan ? Le mode CHROME s'arrête dès qu'il ne l'est plus
        (après l'avoir été, ou passé le délai d'ouverture)."""
        acts = []
        if self.mode != Mode.CHROME:
            return acts
        if front:
            self.chrome_seen = True
        elif self.chrome_seen or t - self.mode_since > CHROME_GRACE_S:
            self.set_mode(Mode.NEUTRAL, t, acts)
            self.last_gesture = ("MODE CHROME QUITTE", t)
        return acts

    # --- dictée Claude (VS Code) ---------------------------------------------
    def ask_confirm(self, kind, t, seconds):
        """Une question attend « envoie » / « annule » (sans « iris ») pendant `seconds`."""
        self.confirm_kind = kind
        self.confirm_until = t + seconds

    def confirming(self, t):
        return t < self.confirm_until

    def dictation_tick(self, t, last_speech_t):
        """Coupe le micro de Claude quand tu as fini de parler : silence de dictation_silence_s après ta
        dernière parole (la durée de la demande n'est pas limitée). Rien dit du tout : on abandonne."""
        if not self.dictating:
            return []
        c = self.cfg
        spoke = last_speech_t > self.dictation_t0 + c.dictation_echo_s
        if spoke and t - last_speech_t >= c.dictation_silence_s:
            self.dictating = False
            self.confirm_until = t + c.send_confirm_s
            self.confirm_kind = "claude"
            self.last_gesture = ("MICRO COUPE : dis ENVOIE ou ANNULE", t)
            return [("vscode_dictation",)]
        if not spoke and t - self.dictation_t0 >= c.dictation_no_speech_s:
            self.dictating = False
            self.last_gesture = ("RIEN ENTENDU : micro coupe", t)
            return [("vscode_dictation",)]
        return []

    def freeze_for_voice(self, t):
        """Plus de gel du curseur sur « iris » (gênant, demande de l'utilisateur, 12/11) : le clic vocal vise
        désormais là où était le curseur quand la commande a commencé (voir _aim). Gardée pour la boucle."""
        return

    def _aim(self, ref_t, acts):
        """Ramène le curseur là où il était à l'instant ref_t (début de « iris clic ») avant de cliquer :
        pendant qu'on parle, la main ou la tête a pu bouger."""
        if not self.mouse or ref_t is None:
            return
        pos = None
        for tt, p in self.cursor_hist:
            if tt <= ref_t:
                pos = p
            else:
                break
        if pos is not None and pos != self.cursor:
            self.cursor = pos
            self._cursor_f = [float(pos[0]), float(pos[1])]
            acts.append(("move", *pos))

    def ask_tick(self, t, last_speech_t):
        """Fin de la question : comme la dictée, après un silence ; rien dit du tout : abandon."""
        if not self.asking:
            return []
        c = self.cfg
        spoke = last_speech_t > self.ask_t0 + c.dictation_echo_s
        if spoke and t - last_speech_t >= c.dictation_silence_s:
            self.asking = False
            self.last_gesture = ("QUESTION ENVOYEE A CLAUDE", t)
            return [("ask_stop",)]
        if not spoke and t - self.ask_t0 >= c.dictation_no_speech_s:
            self.asking = False
            self.last_gesture = ("RIEN ENTENDU : question annulee", t)
            return [("ask_cancel",)]
        return []

    def type_tick(self, t, last_speech_t):
        """« iris type » : fin de la dictée après 2 s de silence, puis 3 s pour envoie / annule."""
        if not self.typing:
            return []
        c = self.cfg
        spoke = last_speech_t > self.type_t0 + c.dictation_echo_s
        if spoke and t - last_speech_t >= c.type_silence_s:
            self.typing = False
            self.confirm_until = t + c.type_confirm_s
            self.confirm_kind = "type"
            self.last_gesture = ("TEXTE ECRIT : ENVOIE ou ANNULE ?", t)
            return [("type_stop",)]
        if not spoke and t - self.type_t0 >= c.dictation_no_speech_s:
            self.typing = False
            self.last_gesture = ("RIEN ENTENDU : dictee annulee", t)
            return [("type_cancel",)]
        return []

    def open_tick(self, t, last_speech_t):
        """« iris ouvre / ferme » : le nom est court, l'écoute se coupe après un court silence.
        Rien dit : abandon sans bruit pour « ferme » (il a déjà retiré la réponse affichée)."""
        if not self.opening:
            return []
        c = self.cfg
        kind = self.open_kind
        close = kind == "close"
        spoke = last_speech_t > self.open_t0 + c.dictation_echo_s
        # un message est une phrase : même silence que la dictée ; un nom (appli, salon) est court
        silence = c.type_silence_s if kind in ("message", "rappel") else c.open_silence_s
        if spoke and t - last_speech_t >= silence:
            self.opening = False
            self.last_gesture = (OPEN_WAIT[kind], t)
            return [(OPEN_STOP[kind],)]
        if not spoke and t - self.open_t0 >= (c.close_no_speech_s if close else c.open_no_speech_s):
            self.opening = False
            if not close:
                self.last_gesture = ({"open": "RIEN ENTENDU : ouvre annule", "message": "RIEN ENTENDU : message annule",
                                      "salon": "RIEN ENTENDU : salon annule",
                                      "rappel": "RIEN ENTENDU : rappel annule",
                                      "timer": "RIEN ENTENDU : timer annule",
                                      "volume": "RIEN ENTENDU : volume inchange"}[kind], t)
            return [("open_cancel",)]
        return []

    def _confirm(self, word, t):
        """Après la dictée : « envoie » (Entrée) ou « annule » (vide le champ). Pas besoin de dire « iris »."""
        self.last_word = (word, t, True)
        if word == "envoie":
            self.confirm_until = -1e9
            self.last_gesture = ("MESSAGE ENVOYE A CLAUDE", t)
            return [("vscode_keys", [["enter"]])]
        if word == "annule":
            self.confirm_until = -1e9
            self.last_gesture = ("MESSAGE EFFACE", t)
            return [("vscode_keys", [["ctrl", "a"], ["backspace"]])]
        if word == "claude":  # redicter : le nouveau texte s'ajoute à la suite
            self.confirm_until = -1e9
            return self.voice_claude(t)
        self.last_gesture = ("dis ENVOIE ou ANNULE", t)
        return []

    def voice_claude(self, t):
        self.dictating = True
        self.dictation_t0 = t
        self.last_gesture = (VOICE_LABELS["claude"], t)
        return [("vscode_dictation",)]

    def _end_scroll(self, t):
        self.voice_scroll_until = -1e9
        self.voice_scroll_armed = False
        self.voice_scroll_since = None
        self._scroll_acc = 0.0
        self.armed = False                    # souris : elle se réarme au centre, comme au départ
        self.arm_since = None
        self.last_gesture = ("DEFILEMENT FINI", t)

    def scrolling(self, t):
        return t < self.voice_scroll_until

    def _scroll_params(self):
        """(demi-bande d'armement, demi-zone neutre, gain) : plus serrés à la tête, qui bouge peu."""
        c = self.cfg
        if self.pointer == "tete":
            return (c.voice_scroll_arm_head, c.voice_scroll_dead_head, c.voice_scroll_gain_head,
                    c.voice_scroll_span_head)
        return c.voice_scroll_arm, c.voice_scroll_dead, c.voice_scroll_gain, c.voice_scroll_span

    def _voice_scroll(self, palm, t, acts):
        """« défile » : comme la souris, rien ne bouge tant que la main n'est pas passée au centre de l'image
        (une bande horizontale : seule la hauteur compte). Ensuite, plus la main est au-dessus / en dessous
        du centre, plus ça défile vite. Fin : « iris défile » redit, « stop », une autre commande, ou (main) main sortie de l'image."""
        c = self.cfg
        arm, dead, gain, span = self._scroll_params()
        if not self.voice_scroll_armed:
            dy = palm[1] - 0.5
            if abs(dy) > arm:
                self.voice_scroll_since = None
                return
            if self.voice_scroll_since is None:
                self.voice_scroll_since = t
            if t - self.voice_scroll_since >= c.arm_hold_s:
                self.voice_scroll_armed = True
                self.voice_scroll_y0, self.voice_scroll_dy = 0.5, dy
                self.last_gesture = ("DEFILE : monte / descends la main", t)
            return
        dy = palm[1] - self.voice_scroll_y0
        if abs(dy) > span:                    # butée : le centre suit, un petit retour suffit pour le neutre
            self.voice_scroll_y0 = palm[1] - math.copysign(span, dy)
            dy = math.copysign(span, dy)
        self.voice_scroll_dy = dy
        if abs(dy) <= dead:
            self._scroll_acc = 0.0
            return
        rate = min((abs(dy) - dead) * gain, c.voice_scroll_max_rate)  # crans / s
        dt = (t - self.prev_t) if self.prev_t is not None else 0.0
        self._scroll_acc += rate * min(dt, 0.2)
        notches = int(self._scroll_acc)
        if notches:
            self._scroll_acc -= notches
            acts.append(("scroll", (notches if dy < 0 else -notches) * c.scroll_notch))

    # --- pour l'affichage ----------------------------------------------------
    def progress(self):
        """(texte, 0..1) de l'action en cours de préparation, ou None."""
        c = self.cfg
        if self.mode == Mode.READING and not self.mouse:
            if self.zone_progress > 0:
                return ("page suivante" if self.zone_side == "next" else "page precedente", self.zone_progress)
            if self.scroll_side is not None:
                return ("defile " + ("haut" if self.scroll_side == "up" else "bas"), self.scroll_progress)
            if c.mouse_bubble and self.bubble is None and not self.need_move and self.still_for > 0.2:
                return ("bulle SOURIS", min(self.still_for / c.mouse_enter_still_s, 1.0))
        elif self.mouse and c.click_menu_on_still and not self.menu.is_open \
                and self.travel >= c.rearm_px \
                and self.still_for > 0.1:
            return ("menu de clic", min(self.still_for / c.dwell_menu_s, 1.0))
        return None
