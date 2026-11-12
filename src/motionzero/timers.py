"""« iris chronomètre » (compte depuis 0) et « iris timer » (compte à rebours, puis sonne).

- « iris chronomètre » : démarre ; redit : arrête, le temps final reste affiché 10 s.
- « iris timer » puis la durée (« cinq minutes », « 1 h 30 », « 45 secondes », Whisper) : compte à rebours ;
  à zéro, une alarme s'affiche et sonne jusqu'à « stop » / « iris merci ». Redit pendant qu'il tourne : annulé.
Fonctions pures (testables) ; l'état vit dans la boucle principale, via le Desk des rappels.
"""
import re
import unicodedata

MAX_S = 24 * 3600
SHOW_FINAL_S = 10.0

_UNITS = {"0": 0, "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
          "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
          "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}
_UNIT_S = {"h": 3600, "heure": 3600, "heures": 3600, "min": 60, "mn": 60, "minute": 60, "minutes": 60,
           "s": 1, "sec": 1, "seconde": 1, "secondes": 1}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("-", " ").replace(",", " ").replace(".", " ").replace("'", " ").replace("’", " ")
    t = re.sub(r"(\d)\s*(h|min|mn|s)\b", r"\1 \2", t)          # « 5min » -> « 5 min »
    t = re.sub(r"(\d+)h(\d+)", r"\1 h \2", t)                     # « 1h30 » -> « 1 h 30 »
    return t


def _number(words, i):
    """Nombre écrit en chiffres ou en lettres à partir de words[i] ; (valeur, mots lus) ou (None, 0)."""
    w = words[i]
    if w.isdigit():
        return int(w), 1
    if w not in _UNITS:
        return None, 0
    val, n = _UNITS[w], 1
    while i + n < len(words):                       # « vingt et un », « dix sept », « quarante cinq »
        nxt = words[i + n]
        if nxt == "et" and i + n + 1 < len(words) and words[i + n + 1] in ("un", "une"):
            return val + 1, n + 2
        if nxt in _UNITS and _UNITS[nxt] < 10 and val >= 10 and val % 10 == 0:
            return val + _UNITS[nxt], n + 1
        break
    return val, n


def parse_duration(text: str) -> int | None:
    """Durée dite -> secondes. « cinq minutes », « 1 h 30 », « une heure et demie », « 90 secondes »,
    « une demi heure », « 2 min 30 ». None si rien de compris, nul ou plus de 24 h."""
    words = _norm(text).split()
    total, pending, i = 0, None, 0
    last_unit = None
    while i < len(words):
        w = words[i]
        if w in ("demi", "demie") and i + 1 < len(words) and words[i + 1] in ("heure", "h"):
            total += 1800
            pending = None                      # « une demi-heure » : le « une » n'est pas un nombre de minutes
            i += 2
            continue
        if w == "quart" and i + 2 < len(words) and words[i + 1] == "d" and words[i + 2] in ("heure", "h"):
            total += 900
            pending = None
            i += 3
            continue
        val, n = _number(words, i)
        if val is not None:
            pending = val
            i += n
            continue
        if w in _UNIT_S and pending is not None:
            total += pending * _UNIT_S[w]
            last_unit, pending = _UNIT_S[w], None
        elif w in ("demi", "demie") and last_unit:
            total += last_unit // 2
        elif w == "quart" and last_unit == 3600:     # « une heure et quart »
            total += 900
        i += 1
    if pending is not None and last_unit in (3600, 60):      # « 1 h 30 » : le reste est l'unité suivante
        total += pending * (60 if last_unit == 3600 else 1)
    elif pending is not None and last_unit is None:
        total += pending * 60                                  # un nombre seul : des minutes
    return total if 0 < total <= MAX_S else None


def fmt(seconds: float) -> str:
    """« 04:07 », « 1:02:09 »."""
    s = max(0, int(seconds + 0.999)) if seconds >= 0 else 0
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def spoken(seconds: int) -> str:
    """« 1 heure 30 minutes », « 45 secondes »."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} heure{'s' if h > 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m > 1 else ''}")
    if s:
        parts.append(f"{s} seconde{'s' if s > 1 else ''}")
    return " ".join(parts) or "0 seconde"


class Timers:
    def __init__(self):
        self.chrono_start = None     # instant (monotonic) du départ, ou None
        self.chrono_final = None     # (durée, instant de l'arrêt) : affiché SHOW_FINAL_S
        self.timer_end = None        # instant de fin du compte à rebours, ou None
        self.timer_total = 0

    def toggle_chrono(self, t):
        """Démarre, ou arrête et renvoie la durée."""
        if self.chrono_start is None:
            self.chrono_start, self.chrono_final = t, None
            return None
        elapsed = t - self.chrono_start
        self.chrono_start, self.chrono_final = None, (elapsed, t)
        return elapsed

    def start_timer(self, t, seconds):
        self.timer_end, self.timer_total = t + seconds, seconds

    def cancel_timer(self):
        running = self.timer_end is not None
        self.timer_end = None
        return running

    def tick(self, t) -> bool:
        """Vrai une fois, quand le compte à rebours arrive à zéro."""
        if self.timer_end is not None and t >= self.timer_end:
            self.timer_end = None
            return True
        return False

    def state(self, t):
        chrono = None
        if self.chrono_start is not None:
            chrono = {"text": fmt(t - self.chrono_start - 0.999), "done": False}
        elif self.chrono_final and t - self.chrono_final[1] < SHOW_FINAL_S:
            chrono = {"text": fmt(self.chrono_final[0] - 0.999), "done": True}
        timer = None if self.timer_end is None else {"text": fmt(self.timer_end - t)}
        return {"chrono": chrono, "timer": timer}
