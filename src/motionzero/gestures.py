"""Détecteurs : pose tenue, balayage, pincement, survol prolongé."""
import math
from collections import deque


class PoseTimer:
    """Durée pendant laquelle une pose est tenue, en ignorant les micro-coupures."""

    def __init__(self, tolerance_s):
        self.tol = tolerance_s
        self.reset()

    def reset(self):
        self.pose = None
        self.since = None
        self.last_seen = None

    def update(self, pose, t):
        if pose == self.pose:
            self.last_seen = t
        elif self.pose is not None and t - self.last_seen <= self.tol:
            pass  # coupure brève : on garde la pose en cours
        else:
            self.pose, self.since, self.last_seen = pose, t, t
        return self.pose, t - self.since


class SwipeDetector:
    """Balayage horizontal. Après un balayage, il faut une main immobile (ou absente) pour réarmer :
    le retour de la main ne déclenche donc pas la page inverse."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.last_fire = -1e9
        self.reset()

    def reset(self):
        self.buf = deque()
        self.armed = True
        self.still_since = None

    def _speed(self, t):
        recent = [p for p in self.buf if t - p[0] <= 0.12]
        if len(recent) < 2:
            return 0.0
        (t0, x0, y0), (t1, x1, y1) = recent[0], recent[-1]
        return math.hypot(x1 - x0, y1 - y0) / max(t1 - t0, 1e-6)

    def update(self, x, y, t, pose_ok=True):
        c = self.cfg
        self.buf.append((t, x, y))
        while self.buf and t - self.buf[0][0] > c.swipe_window_s:
            self.buf.popleft()
        if not self.armed:
            if self._speed(t) < c.swipe_still_speed:
                if self.still_since is None:
                    self.still_since = t
                elif t - self.still_since >= c.swipe_still_s:
                    self.armed = True
                    self.buf.clear()
                    self.buf.append((t, x, y))
            else:
                self.still_since = None
            return None
        if not pose_ok or t - self.last_fire < c.swipe_cooldown_s:
            return None
        t0, x0, y0 = self.buf[0]
        dt = t - t0
        if dt < 0.05:
            return None
        dx, dy = x - x0, y - y0
        if (abs(dx) >= c.swipe_min_dx and abs(dx) / dt >= c.swipe_min_speed
                and abs(dy) <= c.swipe_max_dy_ratio * abs(dx)):
            self.armed = False
            self.still_since = None
            self.last_fire = t
            self.buf.clear()
            # image en miroir : main vers la gauche de l'utilisateur = x diminue = page suivante
            return "next" if dx < 0 else "prev"
        return None


class PinchDetector:
    """Pincement pouce-index (gauche) ou pouce-majeur (droit), avec hystérésis et confirmation."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.down = False
        self.which = None
        self.t_down = None
        self.pending = None
        self.streak = 0
        self.min_d = 1e9

    def _candidate(self, f):
        c = self.cfg
        di, dm = f.pinch_index, f.pinch_middle
        if di < c.pinch_on and (not c.right_click_enabled or di + c.right_click_margin < dm):
            return "left"
        if c.right_click_enabled and dm < c.pinch_on and dm + c.right_click_margin < di:
            return "right"
        return None

    def update(self, f, t):
        c = self.cfg
        if not self.down:
            cand = self._candidate(f)
            if cand is not None and cand == self.pending:
                self.streak += 1
            else:
                self.pending, self.streak = cand, (1 if cand else 0)
            if cand is not None and self.streak >= c.pinch_confirm_frames:
                self.down, self.which, self.t_down = True, cand, t
                self.min_d = f.pinch_index if cand == "left" else f.pinch_middle
                self.pending, self.streak = None, 0
                return ("down", cand)
            return None
        d = f.pinch_index if self.which == "left" else f.pinch_middle
        self.min_d = min(self.min_d, d)
        # relâché quand l'écart remonte nettement au-dessus de son minimum
        # (en index pointé, le pouce replié reste près du majeur : un seuil fixe ne suffit pas)
        # (seuil absolu, ou remontée nette ; un tremblement à 0,36 ne relâche plus)
        released = d > c.pinch_off or (d > c.pinch_on and d - self.min_d > c.pinch_release_rise)
        self.streak = self.streak + 1 if released else 0
        if self.streak >= c.pinch_confirm_frames:
            which, held = self.which, t - self.t_down
            self.reset()
            return ("up", which, held)
        return None


class StillnessDetector:
    """Main immobile : sur une fenêtre de still_window_s, la paume reste dans un rayon still_radius.
    Mesure sur une fenêtre plutôt qu'image par image (tremblements, ~19 img/s)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.buf = deque()
        self.since = None

    def update(self, palm, t):
        c = self.cfg
        self.buf.append((t, palm[0], palm[1]))
        while self.buf and t - self.buf[0][0] > c.still_window_s:
            self.buf.popleft()
        span = self.buf[-1][0] - self.buf[0][0]
        mx = sum(p[1] for p in self.buf) / len(self.buf)
        my = sum(p[2] for p in self.buf) / len(self.buf)
        dev = max(math.hypot(p[1] - mx, p[2] - my) for p in self.buf)
        if span >= c.still_window_s * 0.9 and dev <= c.still_radius:
            if self.since is None:
                self.since = t - span  # immobile depuis le début de la fenêtre
            return t - self.since
        self.since = None
        return 0.0


class ZoneDetector:
    """Page : la paume entre dans une bande au bord de l'image et y reste page_hold_s.
    Une seule page par passage : il faut revenir au centre pour réarmer."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.last_fire = -1e9
        self.reset()

    def reset(self):
        self.armed = True
        self.side = None
        self.since = None

    def update(self, x, t):
        """Renvoie (événement 'next'|'prev'|None, progression 0..1, côté en cours)."""
        c = self.cfg
        if not self.armed:
            if c.page_rearm_lo <= x <= c.page_rearm_hi:
                self.armed = True
            return None, 0.0, None
        side = "next" if x >= c.page_band_right else "prev" if x <= c.page_band_left else None
        if side != self.side:
            self.side, self.since = side, t
        if side is None:
            return None, 0.0, None
        progress = min((t - self.since) / c.page_hold_s, 1.0)
        if progress >= 1.0 and t - self.last_fire >= c.page_refractory_s:
            self.armed = False
            self.last_fire = t
            self.side = None
            return side, 1.0, side
        return None, progress, side


class ScrollDetector:
    """Défilement : paume dans la bande haute / basse de l'image. Après scroll_hold_s,
    un cran toutes les scroll_interval_s tant que la main y reste."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.side = None
        self.since = None
        self.last_tick = None

    def update(self, y, t, allowed=True):
        """Renvoie (crans : +1 haut / -1 bas / 0, progression 0..1, côté 'up'|'down'|None)."""
        c = self.cfg
        side = None
        if allowed:
            side = "up" if y <= c.scroll_band_top else "down" if y >= c.scroll_band_bottom else None
        if side != self.side:
            self.side, self.since, self.last_tick = side, t, None
        if side is None:
            return 0, 0.0, None
        progress = min((t - self.since) / c.scroll_hold_s, 1.0)
        if progress < 1.0:
            return 0, progress, side
        if self.last_tick is None or t - self.last_tick >= c.scroll_interval_s:
            self.last_tick = t
            return (1 if side == "up" else -1), 1.0, side
        return 0, 1.0, side


class RadialMenu:
    """Menu à 4 directions : un petit déplacement de la main choisit une case.
    Rester au centre (ou attendre) annule sans rien faire."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.close()

    def close(self):
        self.is_open = False
        self.center = None
        self.t0 = None
        self.hover = None

    def open(self, palm, t):
        self.is_open, self.center, self.t0, self.hover = True, palm, t, None

    def update(self, palm, t):
        """Renvoie 'left' | 'right' | 'up' | 'down' | 'cancel' | None."""
        c = self.cfg
        dx, dy = palm[0] - self.center[0], palm[1] - self.center[1]
        dist = math.hypot(dx, dy)
        direction = (("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy > 0 else "up"))
        self.hover = direction if dist >= c.menu_neutral else None
        if dist >= c.menu_select:
            self.close()
            return direction
        if t - self.t0 >= c.menu_timeout_s:
            self.close()
            return "cancel"
        return None


class DwellDetector:
    """Clic quand le curseur reste immobile. Après un clic ou une remise à zéro,
    il faut d'abord bouger le curseur : pas de clic en entrant dans le mode souris."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.anchor = None
        self.since = None
        self.fired = True

    def update(self, pos, t):
        c = self.cfg
        if self.anchor is None:
            self.anchor, self.since = pos, t
            return 0.0, False
        if math.hypot(pos[0] - self.anchor[0], pos[1] - self.anchor[1]) > c.dwell_radius_px:
            self.anchor, self.since, self.fired = pos, t, False
            return 0.0, False
        if self.fired:
            return 0.0, False
        progress = (t - self.since) / c.dwell_s
        if progress >= 1.0:
            self.fired = True
            return 1.0, True
        return progress, False
