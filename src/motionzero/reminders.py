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
    '"repeat":null|"daily"|"weekdays"|"weekly","days":[0-6],"alarm":true|false}\n'
    '{"action":"list"}\n'
    '{"action":"cancel","id":"<id d\'un rappel existant>"}\n'
    '{"action":"error","reason":"<pourquoi, en quelques mots>"}\n'
    "Règles : « at » est la PREMIÈRE échéance, en heure locale, toujours dans le futur. "
    "« dans 20 minutes » = maintenant + 20 min. Une heure sans date = aujourd'hui, ou demain si elle est passée. "
    "Une date sans heure = 9:00. « tous les jours » = daily ; « en semaine » = weekdays ; "
    "« tous les lundis et jeudis » = weekly avec days (0 = lundi … 6 = dimanche). "
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
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:6])
    missed: bool = False                     # déclenché pendant que le PC était éteint

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.at, FMT)


def next_after(r: Reminder, after: datetime) -> datetime | None:
    """Prochaine échéance strictement après `after` (None : rappel unique déjà passé)."""
    t = r.when
    if r.repeat is None:
        return t if t > after else None
    step = timedelta(days=1)
    cand = t
    if cand <= after:                                      # saute directement près de `after`
        cand = datetime.combine(after.date(), t.time())
    for _ in range(9):
        if cand > after and (r.repeat == "daily"
                             or (r.repeat == "weekdays" and cand.weekday() < 5)
                             or (r.repeat == "weekly" and cand.weekday() in r.days)):
            return cand
        cand += step
    return None


def describe(r: Reminder, now: datetime) -> str:
    """« tous les jours à 9:00 », « demain à 18:30 », « le 03/12 à 10:00 »."""
    t = r.when
    hm = t.strftime("%H:%M")
    if r.repeat == "daily":
        return f"tous les jours à {hm}"
    if r.repeat == "weekdays":
        return f"en semaine à {hm}"
    if r.repeat == "weekly":
        names = " et ".join(DAYS_FR[d] for d in sorted(r.days)) or "chaque semaine"
        return f"le {names} à {hm}" if len(r.days) != 1 else f"chaque {DAYS_FR[r.days[0]]} à {hm}"
    if t.date() == now.date():
        return f"à {hm}"
    if t.date() == (now + timedelta(days=1)).date():
        return f"demain à {hm}"
    return f"le {t:%d/%m} à {hm}"


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
    r = Reminder(text=text[:120], at=at.strftime(FMT), repeat=repeat, days=days if repeat == "weekly" else [],
                 alarm=bool(data.get("alarm")))
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
            shown = Reminder(**{**asdict(r), "id": uuid.uuid4().hex[:6]})
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
        again = Reminder(text=r.text, at=(now + SNOOZE).strftime(FMT), alarm=r.alarm)
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

    # ---- fil « rappel » ----
    def submit(self, audio):
        import threading
        items = list(self.r.items)
        threading.Thread(target=self._work, args=(audio, items), name="rappel", daemon=True).start()

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
        if self.r.ringing and t - self._last_ring >= ALARM_EVERY_S and self.sounds is not None:
            self._last_ring = t
            self.sounds.play("ALARME")

    def _result(self, core, t, now, kind, obj):
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
            else:
                rest.append(a)
        return rest

    def state(self, t):
        """Pour l'île : rappel affiché, liste, prochain rappel."""
        now = self.clock()
        cur = self.r.active[0] if self.r.active else None
        nxt = self.r.next()
        return {
            "current": None if cur is None else {"text": cur.text, "alarm": cur.alarm, "ringing": self.r.ringing,
                                                 "missed": cur.missed, "more": len(self.r.active) - 1,
                                                 "when": cur.when.strftime("%H:%M")},
            "list": self.list_lines if t < self.list_until else None,
            "next": None if nxt is None else short_when(nxt, now),
        }
