"""Machine à états, gestes v2 : aucune pose de doigts, aucun pincement : méthodes de Core (MainMixin, découpé de core.py, #52)."""
import math

from .hand import compute_features
from .poses import classify, flexion
from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401


class MainMixin:

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
