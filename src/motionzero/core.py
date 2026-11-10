"""Machine à états, gestes v2 : aucune pose de doigts, aucun pincement.
Seules informations utilisées : présence de la main, centre de la paume, mouvement, immobilité.

Modes :
  LECTURE : paume au bord droit / gauche de l'image = page suivante / précédente.
            Main immobile 1,5 s -> bulle « SOURIS ? » ; petit mouvement vers le haut = confirmer.
  SOURIS  : le curseur suit les mouvements de la main (relatif, comme un pavé tactile).
            Main immobile 0,8 s -> menu à 4 directions :
              gauche = clic gauche, droite = clic droit, haut = double clic, bas = retour lecture.
            Main absente 2 s -> retour lecture.
  DESACTIVE : bouton STOP.

Actions renvoyées :
  ("mode", nom) ; ("key", nom) ; ("move", x, y) ; ("click", "left"|"right") ; ("release_all",)
"""
import math
from collections import deque

from .filters import OneEuro
from .gestures import RadialMenu, ScrollDetector, StillnessDetector, ZoneDetector
from .hand import compute_features


class Mode:
    DISABLED = "DESACTIVE"
    READING = "LECTURE"
    MOUSE = "SOURIS"
    IDLE = READING  # compatibilité : l'ancien « repos » est désormais la lecture


MENU_LABELS = {"left": "CLIC GAUCHE", "right": "CLIC DROIT", "up": "DOUBLE CLIC", "down": "LECTURE"}
WAKE_WORD = "iris"
VOICE_HOTKEYS = {"entrée": ["enter"], "copie": ["ctrl", "c"], "colle": ["ctrl", "v"]}
# mot dit -> ce qui se passe (affiché en grand, et dans le panneau d'aide)
VOICE_LABELS = {"clic": "CLIC GAUCHE", "double": "DOUBLE CLIC", "menu": "CLIC DROIT",
                "glisse": "GLISSER (bouton tenu)", "lâche": "LACHER", "entrée": "TOUCHE ENTREE",
                "annule": "TOUCHE ECHAP", "copie": "COPIER (Ctrl+C)", "colle": "COLLER (Ctrl+V)",
                "claude": "MICRO CLAUDE : parle", "retour": "RETOUR A LA FENETRE D'AVANT",
                "tab": "FENETRE SUIVANTE (Alt+Tab)", "discord": "DISCORD", "chrome": "CHROME",
                "mute": "DISCORD COUPE", "démute": "DISCORD RALLUME", "souris": "SOURIS"}


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
        self.mode = Mode.READING
        self.mode_since = -1e9
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
        self.dragging = False                 # bouton tenu par « glisse » : « lâche » toujours écouté
        # voix
        self.listen_until = -1e9
        self.voice_scroll_until = -1e9
        self.voice_scroll_y0 = 0.5
        self._scroll_acc = 0.0
        self.last_word = None       # (mot, t, accepté ?)
        # dictée Claude dans VS Code : micro allumé, puis texte dicté en attente de « envoie » / « annule »
        self.dictating = False
        self.dictation_t0 = -1e9
        self.confirm_until = -1e9
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

    def set_mode(self, mode, t, acts):
        if mode == self.mode:
            return
        if self.mode == Mode.MOUSE:
            acts.append(("release_all",))
        self.mode = mode
        self.mode_since = t
        self._reset()
        acts.append(("mode", mode))
        self.feed.append((f"MODE {mode}", t))

    def disable(self, t):
        acts = [("release_all",)]
        self.set_mode(Mode.DISABLED, t, acts)
        return acts

    def enable(self, t):
        acts = []
        self.set_mode(Mode.READING, t, acts)
        return acts

    # --- boucle ------------------------------------------------------------
    def step(self, pts, t):
        acts = []
        if self.mode == Mode.DISABLED:
            return acts
        if pts is None:
            return self._no_hand(t, acts)
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
        if self.mode == Mode.READING:
            self._reading(palm, t, acts)
        elif self.mode == Mode.MOUSE:
            self._mouse(palm, t, acts)
        self.prev_palm, self.prev_t = palm, t
        return acts

    def _no_hand(self, t, acts):
        self.features = None
        self.palm = None
        if self.last_seen is None:
            return acts
        gone = t - self.last_seen
        if not self.released and gone >= self.cfg.release_absent_s:
            acts.append(("release_all",))
            self.released = True
        if self.mode == Mode.MOUSE and gone >= self.cfg.absent_mouse_s:
            self.set_mode(Mode.READING, t, acts)
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
            self.set_mode(Mode.MOUSE, t, acts)
        elif dist >= c.bubble_cancel_dist or t - t0 >= c.bubble_timeout_s:
            self.bubble = None
            self.need_move = True

    # --- souris ------------------------------------------------------------
    def _gain(self, speed):
        c = self.cfg
        k = min(max((speed - c.gain_speed_lo) / (c.gain_speed_hi - c.gain_speed_lo), 0.0), 1.0)
        return c.gain_min + (c.gain_max - c.gain_min) * k

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
                self.set_mode(Mode.READING, t, acts)
                return
            if choice and choice != "cancel":
                self.last_gesture = (MENU_LABELS[choice], t)
                self.last_click_t = t
            if choice:
                self.travel = 0.0
                self.still.reset()
            return

        if self.prev_palm is not None:
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
        if self.confirming(t):
            return True
        return self.mode != Mode.DISABLED and (t < self.listen_until or self.bubble is not None
                                               or self.menu.is_open)

    def voice(self, word, t, t_start=None):
        """Un mot reconnu (déjà filtré : dit seul). Renvoie les actions."""
        c = self.cfg
        acts = []
        if self.dictating:
            return acts  # le micro de Claude écoute : tes mots sont dictés, ils ne déclenchent rien ici
        if self.confirming(t):
            if word != WAKE_WORD:
                return self._confirm(word, t)
            # « iris » : on passe à autre chose (retour, chrome…). Le message reste dans VS Code :
            # « iris envoie » / « iris annule » marchent toujours, à tout moment.
            self.confirm_until = -1e9
        if word == "stop":  # toujours écouté, prioritaire
            acts.append(("release_all",))
            self.menu.close()
            self.bubble = None
            self.voice_scroll_until = self.listen_until = -1e9
            if self.mode == Mode.MOUSE:
                self.set_mode(Mode.READING, t, acts)
            self.last_gesture = ("STOP", t)
            self.last_word = (word, t, True)
            return acts
        if word == "lâche" and self.dragging:  # bouton tenu : on doit toujours pouvoir le relâcher
            self.dragging = False
            self.last_word = (word, t, True)
            self.last_gesture = (VOICE_LABELS["lâche"], t)
            return [("release", "mouse", "left")]
        if word == WAKE_WORD:
            self.wake_t = t_start if t_start is not None else t
            if self.mode == Mode.DISABLED:
                self.set_mode(Mode.READING, t, acts)
            self.listen_until = t + c.listen_s
            self.last_word = (word, t, True)
            self.last_gesture = ("IRIS : ECOUTE OUVERTE", t)
            return acts
        if not self.listening(t):
            self.last_word = (word, t, False)  # entendu mais écoute fermée : ignoré
            self.last_gesture = (f'"{word}" ignore : dis IRIS avant', t)
            return acts
        self.last_word = (word, t, True)
        # une seule commande par « iris » : la fenêtre se ferme (avant, 8 s prolongées à chaque commande :
        # un mot de la conversation qui suivait — « colle », « chrome » — était exécuté)
        self.listen_until = -1e9
        label = VOICE_LABELS.get(word, word.upper())
        if word in ("clic", "double", "menu", "glisse"):
            acts += self._aim_back(t, t_start)
        if word in ("clic", "double", "menu"):
            if word == "menu":
                acts.append(("click", "right"))
            else:
                acts += [("click", "left")] * (2 if word == "double" else 1)
            self.menu.close()
            self.last_click_t = t
            self.travel = 0.0
        elif word == "glisse":
            acts.append(("press", "mouse", "left"))
            self.dragging = True
        elif word == "lâche":
            acts.append(("release", "mouse", "left"))
        elif word == "défile":
            self.voice_scroll_until = t + c.voice_scroll_s
            self.voice_scroll_y0 = self.palm[1] if self.palm is not None else 0.5
            self._scroll_acc = 0.0
            self.menu.close()
            self.bubble = None
            label = "DEFILE : monte / descends la main"
        elif word in VOICE_HOTKEYS:
            acts.append(("hotkey", VOICE_HOTKEYS[word]))
        elif word == "claude":
            self.dictating = True
            self.dictation_t0 = t
            self.listen_until = -1e9
            self.menu.close()
            self.bubble = None
            acts.append(("vscode_dictation",))
        elif word == "retour":
            acts.append(("window_back",))
        elif word == "envoie":
            acts.append(("vscode_keys", [["enter"]]))      # envoie le message de Claude, à tout moment
            label = "MESSAGE ENVOYE A CLAUDE"
        elif word == "annule":
            acts.append(("annule",))       # vide le message de Claude si VS Code est devant, sinon Échap
            label = "ANNULE"
        elif word == "tab":
            acts.append(("alt_tab",))
        elif word == "souris":
            if self.mode != Mode.MOUSE:
                self.set_mode(Mode.MOUSE, t, acts)
            label = "SOURIS"
        elif word in ("discord", "chrome"):
            acts.append(("open_app", word))
        elif word == "mute":
            acts.append(("discord_mute",))
        elif word == "démute":
            acts.append(("discord_unmute",))
        elif word == "pause":
            acts += [("release_all",)]
            self.set_mode(Mode.DISABLED, t, acts)
            self.listen_until = -1e9
            label = "PAUSE (dis IRIS pour reprendre)"
        self.last_gesture = (label, t)
        return acts

    def _aim_back(self, t, t_start):
        """Clic vocal : la main a pu bouger pendant « iris, clic ». On remet le curseur là où il était
        juste avant le début de la phrase (« iris » s'il vient d'être dit, sinon le mot lui-même)."""
        c = self.cfg
        if self.mode != Mode.MOUSE or not self.cursor_hist:
            return []
        start = t_start if t_start is not None else t
        if 0 <= start - self.wake_t <= c.voice_click_window_s:
            start = self.wake_t
        target = start - c.voice_click_rewind_s
        pos = self.cursor_hist[0][1]
        for ht, hp in self.cursor_hist:
            if ht > target:
                break
            pos = hp
        if pos == self.cursor:
            return []
        self.cursor = pos
        self._cursor_f = [float(pos[0]), float(pos[1])]
        return [("move", *pos)]

    # --- dictée Claude (VS Code) ---------------------------------------------
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
            self.last_gesture = ("MICRO COUPE : dis ENVOIE ou ANNULE", t)
            return [("vscode_dictation",)]
        if not spoke and t - self.dictation_t0 >= c.dictation_no_speech_s:
            self.dictating = False
            self.last_gesture = ("RIEN ENTENDU : micro coupe", t)
            return [("vscode_dictation",)]
        return []

    def _confirm(self, word, t):
        """Après la dictée : « envoie » (Entrée) ou « annule » (vide le champ). Pas besoin de dire « iris »."""
        self.last_word = (word, t, True)
        if word == "envoie":
            self.confirm_until = -1e9
            self.last_gesture = ("MESSAGE ENVOYE A CLAUDE", t)
            return [("vscode_keys", [["enter"]])]
        if word in ("annule", "stop"):
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

    def _voice_scroll(self, palm, t, acts):
        """« défile » : plus la main est loin de sa hauteur de départ, plus ça défile vite."""
        c = self.cfg
        dy = palm[1] - self.voice_scroll_y0
        if abs(dy) <= c.voice_scroll_dead:
            self._scroll_acc = 0.0
            return
        rate = min((abs(dy) - c.voice_scroll_dead) * 60.0, c.voice_scroll_max_rate)  # crans / s
        dt = (t - self.prev_t) if self.prev_t is not None else 0.0
        self._scroll_acc += rate * dt
        notches = int(self._scroll_acc)
        if notches:
            self._scroll_acc -= notches
            acts.append(("scroll", (notches if dy < 0 else -notches) * c.scroll_notch))
            self.voice_scroll_until = max(self.voice_scroll_until, t + 2.0)  # tant qu'on défile, ça reste actif

    # --- pour l'affichage ----------------------------------------------------
    def progress(self):
        """(texte, 0..1) de l'action en cours de préparation, ou None."""
        c = self.cfg
        if self.mode == Mode.READING:
            if self.zone_progress > 0:
                return ("page suivante" if self.zone_side == "next" else "page precedente", self.zone_progress)
            if self.scroll_side is not None:
                return ("defile " + ("haut" if self.scroll_side == "up" else "bas"), self.scroll_progress)
            if c.mouse_bubble and self.bubble is None and not self.need_move and self.still_for > 0.2:
                return ("bulle SOURIS", min(self.still_for / c.mouse_enter_still_s, 1.0))
        elif self.mode == Mode.MOUSE and c.click_menu_on_still and not self.menu.is_open \
                and self.travel >= c.rearm_px \
                and self.still_for > 0.1:
            return ("menu de clic", min(self.still_for / c.dwell_menu_s, 1.0))
        return None
