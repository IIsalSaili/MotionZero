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
from .poses import PoseVoter, classify, flexion
from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401
from .core_voix import VoixMixin
from .core_commandes import CommandesMixin
from .core_ecoute import EcouteMixin


class Core(VoixMixin, CommandesMixin, EcouteMixin):
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
    def _gain(self, speed, dt=None):
        c = self.cfg
        if self.pointer == "tete":
            return head_gain(self._head_speed(speed, dt), c.head_speed_lo, c.head_speed_hi,
                             c.head_gain_min, c.head_gain_max)
        k = min(max((speed - c.gain_speed_lo) / (c.gain_speed_hi - c.gain_speed_lo), 0.0), 1.0)
        return c.gain_min + (c.gain_max - c.gain_min) * k

    def _head_speed(self, speed, dt):
        """Vitesse de la tête moyennée (~0,15 s) : partir de l'arrêt reste lent (visée), seul un geste qui dure
        accélère. Notée pour le réglage (journal « tete vitesse »)."""
        a = 1.0 if not dt else min(dt / max(self.cfg.head_speed_tau, 1e-3), 1.0)
        self.head_speed = self.head_speed + a * (speed - self.head_speed)
        self.head_speeds.append(self.head_speed)
        return self.head_speed

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
            gain = self._gain(math.hypot(dx, dy) / dt, dt)
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
        """(demi-bande d'armement, demi-zone neutre, écart de vitesse maximale, butée) : la tête bouge peu."""
        c = self.cfg
        if self.pointer == "tete":
            return (c.voice_scroll_arm_head, c.voice_scroll_dead_head, c.voice_scroll_span_head,
                    c.voice_scroll_span_head)
        return c.voice_scroll_arm, c.voice_scroll_dead, c.voice_scroll_full, c.voice_scroll_span

    def scroll_rate(self, dy, dead, full):
        """Crans / s : 0 dans la zone verte, lent juste après, de plus en plus vite vers les extrêmes (carré)."""
        c = self.cfg
        if abs(dy) <= dead:
            return 0.0
        u = min((abs(dy) - dead) / max(full - dead, 1e-6), 1.0)
        top = c.voice_scroll_max_rate_head if self.pointer == "tete" else c.voice_scroll_max_rate
        return c.voice_scroll_min_rate + (top - c.voice_scroll_min_rate) * u * u

    def _voice_scroll(self, palm, t, acts):
        """« défile » : comme la souris, rien ne bouge tant que la main n'est pas passée au centre de l'image
        (une bande horizontale : seule la hauteur compte). Ensuite, plus la main est au-dessus / en dessous
        du centre, plus ça défile vite. Fin : « iris défile » redit, « stop », une autre commande, ou (main) main sortie de l'image."""
        c = self.cfg
        arm, dead, full, span = self._scroll_params()
        if not self.voice_scroll_armed and self.pointer == "tete":
            # tête : le centre = la tête au moment de « défile » (la référence de la souris peut être ancienne)
            self.voice_scroll_armed = True
            self.voice_scroll_y0, self.voice_scroll_dy = palm[1], 0.0
            self.last_gesture = ("DEFILE : leve / baisse la tete", t)
            return
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
        rate = self.scroll_rate(dy, dead, full)
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
