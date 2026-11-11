"""« Iris calendrier » (issue #21) : la semaine en 7 cartes, le mois en ruban, un jour en grand.

À la voix seulement, calendrier ouvert (sans « iris » devant) :
- « suivant » / « précédent » : semaine suivante / précédente (ou jour, si un jour est ouvert en grand) ;
- « lundi » … « dimanche » : ce jour en grand ; « aujourd'hui » : retour à aujourd'hui ;
- « premier », « deux » … « trente-et-un » : la semaine de ce jour du mois affiché ;
- « ferme » / « merci » / « stop » : ferme. Une minute sans commande : se ferme seul.
Fonctions pures (testables) ; l'état vit dans la boucle principale, via le Desk des rappels.
"""
from datetime import date, datetime, timedelta

from .reminders import DAYS_FR, Reminder, _day_ok, _hours

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]
NUMBERS = ["premier", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
           "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf", "vingt", "vingt-et-un",
           "vingt-deux", "vingt-trois", "vingt-quatre", "vingt-cinq", "vingt-six", "vingt-sept", "vingt-huit",
           "vingt-neuf", "trente", "trente-et-un"]
DAY_OF = {w: i + 1 for i, w in enumerate(NUMBERS)}
WEEKDAY_OF = {d: i for i, d in enumerate(DAYS_FR)}
WORDS = ["suivant", "précédent", "aujourd'hui"] + DAYS_FR + NUMBERS     # actifs seulement calendrier ouvert
MAX_ITEMS = 3            # rendez-vous par carte ; au-delà : « + N autres »


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def occurrences(r: Reminder, day: date):
    """Horaires de `r` ce jour-là (liste de « HH:MM »), vide s'il ne tombe pas ce jour."""
    start = r.when.date()
    if r.repeat is None:
        if day != start:
            return []
        return [h.strftime("%H:%M") for h in _hours(r)] if r.times else [r.when.strftime("%H:%M")]
    if day < start or not _day_ok(r, day):
        return []
    return [h.strftime("%H:%M") for h in _hours(r)]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def day_cards(items, day: date):
    """(rendez-vous, routines) d'un jour : seuls les rappels uniques sont des rendez-vous ; les répétés
    (réveil de semaine, médicaments, poignets toutes les 2 h) sont résumés en bas de la carte."""
    events, routine = [], []
    for r in items:
        hs = occurrences(r, day)
        if not hs:
            continue
        if r.repeat is None:
            events += [{"t": h, "txt": _cap(r.text), "alarm": r.alarm} for h in hs]
        elif len(hs) == 1:
            routine.append(f"{hs[0]} {r.text}")
        else:
            routine.append(f"{r.text} × {len(hs)}\n{hs[0]} → {hs[-1]}")
    events.sort(key=lambda e: e["t"])
    return events, routine


def day_detail(items, day: date):
    """Tout ce qui tombe ce jour-là, routines comprises, dans l'ordre des heures."""
    out = []
    for r in items:
        for h in occurrences(r, day):
            out.append({"t": h, "txt": _cap(r.text), "alarm": r.alarm, "routine": r.repeat is not None})
    return sorted(out, key=lambda e: e["t"])


class Calendar:
    def __init__(self):
        self.open = False
        self.week = None          # lundi de la semaine affichée
        self.detail = None        # jour ouvert en grand, ou None
        self.focus = None         # jour mis en avant (« iris 18 »)

    def show(self, today: date):
        self.open, self.week, self.detail, self.focus = True, monday(today), None, today

    def close(self):
        self.open, self.detail = False, None

    def command(self, word: str, today: date) -> bool:
        """Applique une commande ; False si le mot n'est pas une commande du calendrier."""
        if word in ("suivant", "précédent"):
            step = 1 if word == "suivant" else -1
            if self.detail is not None:
                self.detail += timedelta(days=step)
                self.week = monday(self.detail)
            else:
                self.week += timedelta(weeks=step)
                self.focus = None
            return True
        if word == "aujourd'hui":
            self.show(today)
            return True
        if word in WEEKDAY_OF:
            self.detail = self.week + timedelta(days=WEEKDAY_OF[word])
            return True
        if word in DAY_OF:
            ref = self.week + timedelta(days=3)               # le mois affiché : celui du jeudi de la semaine
            try:
                target = date(ref.year, ref.month, DAY_OF[word])
            except ValueError:                                  # « trente-et-un » en novembre
                return True
            self.week, self.detail, self.focus = monday(target), None, target
            return True
        return False

    def view(self, items, now: datetime):
        """Ce que dessine l'île."""
        today = now.date()
        days = [self.week + timedelta(days=i) for i in range(7)]
        ref = self.week + timedelta(days=3)
        first = date(ref.year, ref.month, 1)
        nxt = date(ref.year + (ref.month == 12), ref.month % 12 + 1, 1)
        strip = []
        d = first
        while d < nxt:
            events, _ = day_cards(items, d)
            kind = "a" if any(e["alarm"] for e in events) else ("r" if events else None)
            strip.append({"n": d.day, "kind": kind, "week": days[0] <= d <= days[-1], "today": d == today})
            d += timedelta(days=1)
        cards = []
        for d in days:
            events, routine = day_cards(items, d)
            cards.append({"name": DAYS_FR[d.weekday()].upper(), "n": d.day, "today": d == today, "past": d < today,
                          "focus": d == self.focus, "items": events[:MAX_ITEMS],
                          "more": max(0, len(events) - MAX_ITEMS), "routine": routine})
        detail = None
        if self.detail is not None:
            dd = self.detail
            detail = {"title": f"{DAYS_FR[dd.weekday()].capitalize()} {dd.day} {MONTHS_FR[dd.month - 1]}",
                      "today": dd == today, "items": day_detail(items, dd)}
        a, b = days[0], days[-1]
        title = (f"{a.day} → {b.day} {MONTHS_FR[b.month - 1]}" if a.month == b.month
                 else f"{a.day} {MONTHS_FR[a.month - 1]} → {b.day} {MONTHS_FR[b.month - 1]}")
        return {"title": title, "month": f"{MONTHS_FR[ref.month - 1].capitalize()} {ref.year}",
                "strip": strip, "days": cards, "detail": detail}
