"""Rappels et alarmes (issue #20).

- « iris rappel » + phrase libre : Whisper transcrit, Claude Haiku la traduit en JSON (créer / lister /
  annuler), Iris répète ce qu'elle a compris et attend « envoie » ou « annule ».
- Un rappel déclenché reste affiché jusqu'à « iris merci » ; « iris plus tard » le décale de 10 min ;
  une alarme sonne en boucle jusqu'à « stop » (ou « merci »).
- Tout est gardé dans reminders.json (non versionné) : les rappels survivent à un redémarrage ; ceux
  passés pendant que le PC était éteint sont affichés au démarrage, marqués « manqué ».
- L'objet Reminders appartient à la boucle principale : les autres fils ne lui parlent que par une queue.
"""
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger("motionzero.reminders")

SNOOZE = timedelta(minutes=10)
REPEATS = (None, "daily", "weekdays", "weekly")
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FMT = "%Y-%m-%dT%H:%M"

PARSE_SYSTEM = (
    "Tu convertis une demande de rappel dictée en français en UN objet JSON, sans aucun autre texte. "
    "Formats possibles :\n"
    '{"action":"create","text":"<ce qu\'il faut rappeler, court>","at":"AAAA-MM-JJTHH:MM",'
    '"repeat":null|"daily"|"weekdays"|"weekly","days":[0-6],"times":["HH:MM",...],"alarm":true|false}\n'
    '{"action":"list"}\n'
    '{"action":"cancel","id":"<id d\'un rappel existant>"}\n'
    '{"action":"error","reason":"<pourquoi, en quelques mots>"}\n'
    "Règles : « at » est la PREMIÈRE échéance, en heure locale, toujours dans le futur. "
    "« dans 20 minutes » = maintenant + 20 min. Une heure sans date = aujourd'hui, ou demain si elle est passée. "
    "Une date sans heure = 9:00. « tous les jours » = daily ; « en semaine » = weekdays ; "
    "« tous les lundis et jeudis » = weekly avec days (0 = lundi … 6 = dimanche). "
    "Plusieurs horaires dans la même journée (« toutes les 2 heures à partir de midi », « à 9 h et à 21 h », "
    "« toutes les 30 minutes entre 14 h et 16 h ») : « times » liste TOUS les horaires de la journée ; sans heure "
    "de fin, s'arrêter à 22:00 inclus ; sans jour précisé, c'est tous les jours (daily). Un seul horaire : times vide. "
    "alarm = true seulement si la demande parle de réveil, d'alarme ou de sonnerie. "
    "« text » reprend l'objet du rappel sans les mots de temps (« appeler le médecin »). "
    "Pour annuler, choisis l'id du rappel existant qui correspond ; aucun ne correspond : error. "
    "Demande incompréhensible ou sans moment : error."
)


@dataclass
class Reminder:
    text: str
    at: str                                  # prochaine échéance, heure locale « AAAA-MM-JJTHH:MM »
    repeat: str | None = None
    days: list[int] = field(default_factory=list)
    alarm: bool = False
    times: list[str] = field(default_factory=list)   # plusieurs horaires par jour (« HH:MM ») ; vide : celui de `at`
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:6])
    missed: bool = False                     # déclenché pendant que le PC était éteint

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.at, FMT)


def _day_ok(r: Reminder, day) -> bool:
    return (r.repeat == "daily" or (r.repeat == "weekdays" and day.weekday() < 5)
            or (r.repeat == "weekly" and day.weekday() in r.days))


def _hours(r: Reminder):
    return sorted(datetime.strptime(h, "%H:%M").time() for h in r.times) if r.times else [r.when.time()]


def next_after(r: Reminder, after: datetime) -> datetime | None:
    """Prochaine échéance strictement après `after` (None : plus rien à venir).
    Plusieurs horaires (`times`) : le premier encore à venir ; sans répétition, seulement le jour de `at`."""
    t = r.when
    if r.repeat is None:
        if not r.times:
            return t if t > after else None
        for h in _hours(r):
            cand = datetime.combine(t.date(), h)
            if cand > after and cand >= t:
                return cand
        return None
    day = max(t.date(), after.date())
    for _ in range(9):
        if _day_ok(r, day):
            for h in _hours(r):
                cand = datetime.combine(day, h)
                if cand > after and cand >= t:
                    return cand
        day += timedelta(days=1)
    return None


def hours_label(r: Reminder) -> str:
    """« 09:00 », « 09:00 et 21:00 », « toutes les 2 h de 12:00 à 22:00 »."""
    hs = _hours(r)
    txt = [h.strftime("%H:%M") for h in hs]
    if len(hs) == 1:
        return f"à {txt[0]}"
    mins = [h.hour * 60 + h.minute for h in hs]
    gaps = {b - a for a, b in zip(mins, mins[1:])}
    if len(hs) >= 3 and len(gaps) == 1:
        g = gaps.pop()
        step = f"{g // 60} h" if g % 60 == 0 else (f"{g} min" if g < 60 else f"{g // 60} h {g % 60:02d}")
        return f"toutes les {step} de {txt[0]} à {txt[-1]}"
    return "à " + ", ".join(txt[:-1]) + " et " + txt[-1]


def describe(r: Reminder, now: datetime) -> str:
    """« tous les jours à 9:00 », « demain à 18:30 », « le 03/12 à 10:00 »."""
    t = r.when
    hm = hours_label(r) if (r.repeat or r.times) else f"à {t:%H:%M}"
    if r.repeat == "daily":
        return f"tous les jours {hm}"
    if r.repeat == "weekdays":
        return f"en semaine {hm}"
    if r.repeat == "weekly":
        names = " et ".join(DAYS_FR[d] for d in sorted(r.days)) or "chaque semaine"
        return f"le {names} {hm}" if len(r.days) != 1 else f"chaque {DAYS_FR[r.days[0]]} {hm}"
    if t.date() == now.date():
        return hm if r.times else f"à {t:%H:%M}"
    if t.date() == (now + timedelta(days=1)).date():
        return f"demain {hm}"
    return f"le {t:%d/%m} {hm}"


def short_when(r: Reminder, now: datetime) -> str:
    """Pour la petite pastille : « 18:30 », « mar. 9:00 »."""
    t = r.when
    if t.date() == now.date():
        return t.strftime("%H:%M")
    return f"{DAYS_FR[t.weekday()][:3]}. {t:%H:%M}"


def extract_json(reply: str) -> dict:
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        raise ValueError("pas de JSON")
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON inattendu")
    return data


def validate(data: dict, now: datetime, known_ids) -> tuple[str, object]:
    """Réponse de Haiku -> ("create", Reminder) | ("list", None) | ("cancel", id) | ("error", raison)."""
    action = data.get("action")
    if action == "list":
        return "list", None
    if action == "cancel":
        rid = str(data.get("id", ""))
        return ("cancel", rid) if rid in known_ids else ("error", "rappel introuvable")
    if action == "error":
        return "error", str(data.get("reason") or "pas compris")[:60]
    if action != "create":
        return "error", "pas compris"
    text = str(data.get("text") or "").strip()
    if not text:
        return "error", "rappel sans texte"
    try:
        at = datetime.strptime(str(data.get("at", ""))[:16], FMT)
    except ValueError:
        return "error", "heure incomprise"
    repeat = data.get("repeat")
    if repeat not in REPEATS:
        return "error", "répétition incomprise"
    days = sorted({int(d) for d in (data.get("days") or []) if str(d).isdigit() and 0 <= int(d) <= 6})
    if repeat == "weekly" and not days:
        return "error", "jours de la semaine manquants"
    times = set()
    for h in data.get("times") or []:
        try:
            times.add(datetime.strptime(str(h).strip()[:5], "%H:%M").strftime("%H:%M"))
        except ValueError:
            return "error", "horaires incompris"
    if len(times) > 48:
        return "error", "trop d'horaires dans la journée"
    times = sorted(times) if len(times) > 1 else []
    if times:                     # la première échéance est le premier horaire de la liste, ce jour-là
        at = datetime.combine(at.date(), datetime.strptime(times[0], "%H:%M").time())
    r = Reminder(text=text[:120], at=at.strftime(FMT), repeat=repeat, days=days if repeat == "weekly" else [],
                 alarm=bool(data.get("alarm")), times=times)
    nxt = next_after(r, now)
    if nxt is None:
        return "error", "cette heure est déjà passée"
    r.at = nxt.strftime(FMT)
    return "create", r


def parse_prompt(phrase: str, now: datetime, items) -> str:
    existing = [{"id": r.id, "text": r.text, "quand": describe(r, now)} for r in items]
    return (f"Maintenant : {DAYS_FR[now.weekday()]} {now:%Y-%m-%d %H:%M}.\n"
            f"Rappels existants : {json.dumps(existing, ensure_ascii=False)}\n"
            f"Demande : « {phrase} »")


class Reminders:
    def __init__(self, path):
        self.path = path
        self.items: list[Reminder] = []       # à venir
        self.active: list[Reminder] = []      # déclenchés, affichés jusqu'à « merci »
        self.ringing = False                  # alarme en train de sonner
        self.load_error = None

    # ---- fichier ----
    def load(self, now: datetime):
        """Charge le fichier ; les échéances passées pendant l'absence deviennent des rappels « manqués »."""
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            self.items = [Reminder(**r) for r in raw.get("items", [])]
            self.active = [Reminder(**r) for r in raw.get("active", [])]
        except FileNotFoundError:
            return self
        except (OSError, ValueError, TypeError) as e:
            log.exception("rappels illisibles")
            self.load_error = "RAPPELS ILLISIBLES : fichier mis de cote"
            try:
                os.replace(self.path, self.path + ".abime")
            except OSError:
                pass
            self.items, self.active = [], []
            return self
        for r in self.tick(now):
            r.missed = True
        self.ringing = False                  # une alarme manquée ne sonne pas au démarrage
        return self

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"items": [asdict(r) for r in self.items], "active": [asdict(r) for r in self.active]},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            log.exception("rappels non enregistres")

    # ---- boucle principale ----
    def add(self, r: Reminder):
        self.items.append(r)
        self.items.sort(key=lambda x: x.at)
        self.save()

    def cancel(self, rid: str) -> Reminder | None:
        for r in self.items:
            if r.id == rid:
                self.items.remove(r)
                self.save()
                return r
        return None

    def tick(self, now: datetime) -> list[Reminder]:
        """Rappels arrivés à échéance : passés dans `active` ; les répétés sont reprogrammés."""
        fired = []
        for r in list(self.items):
            if r.when > now:
                continue
            shown = Reminder(**{**asdict(r), "id": uuid.uuid4().hex[:6], "times": []})
            fired.append(shown)
            self.active.append(shown)
            nxt = next_after(r, now) if r.repeat else None
            if nxt is None:
                self.items.remove(r)
            else:
                r.at = nxt.strftime(FMT)
            if r.alarm:
                self.ringing = True
        if fired:
            self.items.sort(key=lambda x: x.at)
            self.save()
        return fired

    def dismiss(self) -> Reminder | None:
        """« iris merci » : le rappel affiché disparaît (et l'alarme se tait)."""
        self.ringing = False
        if not self.active:
            return None
        r = self.active.pop(0)
        self.save()
        return r

    def snooze(self, now: datetime) -> Reminder | None:
        """« iris plus tard » : revient dans 10 min."""
        self.ringing = False
        if not self.active:
            return None
        r = self.active.pop(0)
        again = Reminder(text=r.text, at=(now + SNOOZE).strftime(FMT), alarm=r.alarm)   # une seule fois
        self.add(again)
        return again

    def silence(self):
        self.ringing = False

    def next(self) -> Reminder | None:
        return self.items[0] if self.items else None


CONFIRM_S = 20.0          # temps pour dire « envoie » / « annule » après la répétition d'Iris
LIST_S = 15.0             # durée d'affichage de la liste
ALARM_EVERY_S = 1.5       # sonnerie de l'alarme
TICK_S = 1.0              # vérification des échéances


def _plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


class Desk:
    """Chef d'orchestre des rappels. `events`, `actions` et `state` sont appelés par la boucle principale
    seulement ; `submit` lance le travail lent (Whisper + Haiku) dans un fil qui ne rend compte que par `_q`."""

    def __init__(self, reminders, speaker=None, sounds=None, bot=None, clock=datetime.now,
                 ask=None, transcribe=None):
        import queue
        self.r = reminders
        self.speaker, self.sounds, self.bot = speaker, sounds, bot
        self.clock = clock
        self._ask = ask
        self._transcribe = transcribe
        self._q = queue.Queue()
        self.pending = None                    # ("create", Reminder) | ("cancel", Reminder) en attente d'« envoie »
        self.list_until = -1e9
        self.list_lines = []
        self._last_tick = -1e9
        self._last_ring = -1e9
        self._announced_missed = False
        from .calendar_view import Calendar
        from .timers import Timers
        self.cal = Calendar()
        self.timers = Timers()

    # ---- fil « rappel » ----
    def submit(self, audio):
        import threading
        items = list(self.r.items)
        threading.Thread(target=self._work, args=(audio, items), name="rappel", daemon=True).start()

    def submit_timer(self, audio):
        import threading
        threading.Thread(target=self._work_timer, args=(audio,), name="timer", daemon=True).start()

    def _work_timer(self, audio):
        from .timers import parse_duration
        try:
            phrase = (self._transcribe(audio) or "").strip(" .")
        except Exception:
            log.exception("transcription timer")
            phrase = ""
        seconds = parse_duration(phrase) if phrase else None
        log.info("timer : %s -> %s", phrase, seconds)
        self._q.put(("timer", seconds) if seconds else ("error", "duree incomprise" if phrase else "rien entendu"))

    def _work(self, audio, items):
        try:
            phrase = (self._transcribe(audio) or "").strip(" .")
        except Exception:
            log.exception("transcription rappel")
            phrase = ""
        if not phrase:
            self._q.put(("error", "rien entendu"))
            return
        now = self.clock()
        try:
            reply = self._ask(parse_prompt(phrase, now, items))
            result = validate(extract_json(reply), now, {r.id for r in items})
        except Exception as e:
            log.warning("rappel incompris (%s) : %s", e.__class__.__name__, phrase)
            result = ("error", "Haiku indisponible" if isinstance(e, RuntimeError) else "pas compris")
        log.info("rappel : %s -> %s", phrase, result[0])
        self._q.put(result)

    # ---- boucle principale ----
    def _say(self, text):
        if self.speaker is not None:
            self.speaker.say(text, force=True)

    def _notify(self, text):
        if self.bot is not None and self.bot.connected:
            self.bot.send({"t": "notify", "text": text})

    def events(self, core, t):
        """Résultats de Haiku, échéances, sonnerie de l'alarme."""
        import queue
        now = self.clock()
        if self.r.load_error:
            core.last_gesture = (self.r.load_error, t)
            self.r.load_error = None
        if not self._announced_missed:
            self._announced_missed = True
            missed = [x for x in self.r.active if x.missed]
            if missed:
                n, x = len(missed), "s" if len(missed) > 1 else ""
                self._say(f"{n} rappel{x} manqué{x} pendant ton absence.")
        while True:
            try:
                kind, obj = self._q.get_nowait()
            except queue.Empty:
                break
            self._result(core, t, now, kind, obj)
        if t - self._last_tick >= TICK_S:
            self._last_tick = t
            for x in self.r.tick(now):
                log.info("rappel declenche : %s", x.text)
                if self.sounds is not None:
                    self.sounds.play("ALARME" if x.alarm else "RAPPEL")
                    if x.alarm:
                        self._last_ring = t           # la sonnerie en boucle reprend 1,5 s plus tard
                self._say(("Alarme : " if x.alarm else "Rappel : ") + x.text)
                self._notify(("Alarme : " if x.alarm else "Rappel : ") + x.text)
        if self.timers.tick(t):
            from .timers import spoken
            what = f"Timer de {spoken(self.timers.timer_total)} terminé"
            self.r.active.insert(0, Reminder(text=what, at=now.strftime(FMT), alarm=True))
            self.r.ringing = True
            self._last_ring = t
            if self.sounds is not None:
                self.sounds.play("ALARME")
            self._say(what)
            self._notify("Timer : " + what)
            log.info("%s", what)
        core.timer_running = self.timers.timer_end is not None
        if self.r.ringing and t - self._last_ring >= ALARM_EVERY_S and self.sounds is not None:
            self._last_ring = t
            self.sounds.play("ALARME")            # boucle déjà en cours : sans effet (rien ne repart de zéro)
        elif not self.r.ringing and self.sounds is not None:
            stop = getattr(self.sounds, "stop_alarm", None)
            if stop is not None:
                stop()                            # « stop », « merci », « plus tard » : la sonnerie se tait

    def _result(self, core, t, now, kind, obj):
        if kind == "timer":
            from .timers import fmt, spoken
            self.timers.start_timer(t, obj)
            core.timer_running = True
            core.last_gesture = (f"TIMER {fmt(obj)}", t)
            self._say(f"Timer de {spoken(obj)}.")
            return
        if kind == "create":
            self.pending = ("create", obj)
            core.ask_confirm("rappel", t, CONFIRM_S)
            what = f"{describe(obj, now)} : {obj.text}"
            label = "Alarme" if obj.alarm else "Rappel"
            core.last_gesture = (f"{label.upper()} {what}"[:60], t)
            self._say(f"{label} {what}. Dis envoie pour valider.")
        elif kind == "cancel":
            target = next((x for x in self.r.items if x.id == obj), None)
            if target is None:
                core.last_gesture = ("RAPPEL INTROUVABLE", t)
                return
            self.pending = ("cancel", target)
            core.ask_confirm("rappel", t, CONFIRM_S)
            core.last_gesture = (f"SUPPRIMER : {target.text} ?"[:60], t)
            self._say(f"Supprimer le rappel {target.text} ? Dis envoie pour confirmer.")
        elif kind == "list":
            items = self.r.items[:6]
            if not items:
                core.last_gesture = ("AUCUN RAPPEL", t)
                self._say("Tu n'as aucun rappel.")
                return
            self.list_lines = [f"{describe(x, now)} · {x.text}" for x in items]
            self.list_until = t + LIST_S
            self._say(f"{_plural(len(self.r.items), 'rappel')}. "
                      + ". ".join(f"{x.text}, {describe(x, now)}" for x in items))
        else:
            core.last_gesture = (f"RAPPEL : {obj}".upper()[:60], t)
            self._say(f"Rappel : {obj}.")

    def actions(self, acts, core, t):
        """Actions vocales des rappels ; renvoie les autres."""
        rest = []
        now = self.clock()
        for a in acts:
            k = a[0]
            if k == "rappel_ok":
                if self.pending is None:
                    continue
                what, r = self.pending
                self.pending = None
                if what == "create":
                    self.r.add(r)
                    core.last_gesture = (f"RAPPEL ENREGISTRE : {describe(r, now)}"[:60], t)
                else:
                    self.r.cancel(r.id)
                    core.last_gesture = ("RAPPEL SUPPRIME", t)
            elif k == "rappel_non":
                self.pending = None
                core.last_gesture = ("RAPPEL ABANDONNE", t)
            elif k == "rappel_merci":
                self.list_until = -1e9
                done = self.r.dismiss()
                core.last_gesture = ("RAPPEL VALIDE" if done else "AUCUN RAPPEL AFFICHE", t)
            elif k == "rappel_tard":
                again = self.r.snooze(now)
                core.last_gesture = (f"RAPPEL A {again.when:%H:%M}" if again else "AUCUN RAPPEL AFFICHE", t)
            elif k == "alarm_stop":
                self.r.silence()
            elif k == "chrono":
                from .timers import spoken
                elapsed = self.timers.toggle_chrono(t)
                if elapsed is None:
                    core.last_gesture = ("CHRONOMETRE LANCE", t)
                else:
                    core.last_gesture = ("CHRONOMETRE ARRETE", t)
                    self._say(spoken(int(elapsed)) + ".")
            elif k == "timer_cancel":
                self.timers.cancel_timer()
                core.timer_running = False
            elif k == "cal_open":
                self.cal.show(now.date())
                self.list_until = -1e9
            elif k == "cal_close":
                self.cal.close()
            elif k == "cal":
                if not self.cal.open:
                    self.cal.show(now.date())
                self.cal.command(a[1], now.date(), t)
            else:
                rest.append(a)
        return rest

    def state(self, t, calendar_open=True):
        """Pour l'île : rappel affiché, liste, calendrier, prochain rappel."""
        now = self.clock()
        if self.cal.open and not calendar_open:      # fermé par inactivité (Core) : on suit
            self.cal.close()
        cur = self.r.active[0] if self.r.active else None
        nxt = self.r.next()
        return {
            "current": None if cur is None else {"text": cur.text, "alarm": cur.alarm, "ringing": self.r.ringing,
                                                 "missed": cur.missed, "more": len(self.r.active) - 1,
                                                 "when": cur.when.strftime("%H:%M")},
            "list": self.list_lines if t < self.list_until else None,
            "calendar": self.cal.view(self.r.items, now) if self.cal.open else None,
            "timers": self.timers.state(t),
            "next": None if nxt is None else short_when(nxt, now),   # pour la future vue calendrier
        }
