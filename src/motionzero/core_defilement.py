"""Machine à états, gestes v2 : aucune pose de doigts, aucun pincement : méthodes de Core (DefilementMixin, découpé de core.py, #52)."""
import math

from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401


class DefilementMixin:

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
        if self.mouse and c.click_menu_on_still and not self.menu.is_open \
                and self.travel >= c.rearm_px \
                and self.still_for > 0.1:
            return ("menu de clic", min(self.still_for / c.dwell_menu_s, 1.0))
        return None
