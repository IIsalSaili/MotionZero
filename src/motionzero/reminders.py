"""Rappels et alarmes (issue #20).

- « iris rappel » + phrase libre : Whisper transcrit, Claude Haiku la traduit en JSON (créer / lister /
  annuler), Iris répète ce qu'elle a compris et attend « envoie » ou « annule ».
- Un rappel déclenché reste affiché jusqu'à « iris merci » ; « iris plus tard » le décale de 10 min ;
  une alarme sonne en boucle jusqu'à « stop » (ou « merci »).
- Tout est gardé dans reminders.json (non versionné) : les rappels survivent à un redémarrage ; ceux
  passés pendant que le PC était éteint sont affichés au démarrage, marqués « manqué ».
- L'objet Reminders appartient à la boucle principale : les autres fils ne lui parlent que par une queue.
"""
import logging
from datetime import datetime
from .reminders_base import (ALARM_EVERY_S, CONFIRM_S, DAYS_FR, FMT, LIST_S, PARSE_SYSTEM, REPEATS, Reminder, Reminders, SNOOZE, TICK_S, _day_ok, _hours, _plural, describe, extract_json, hours_label, next_after, parse_prompt, pending_text, short_when, validate)  # noqa: F401

log = logging.getLogger("motionzero.reminders")


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
    def submit(self, audio, confirm=True):
        """confirm=False (« iris instruction », 17/11) : créé ou supprimé tout de suite, sans « envoie »."""
        import threading
        items = list(self.r.items)
        threading.Thread(target=self._work, args=(audio, items, confirm), name="rappel", daemon=True).start()

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

    def _work(self, audio, items, confirm=True):
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
            result = ("error", "Iris indisponible" if isinstance(e, RuntimeError) else "pas compris")
        log.info("rappel : %s -> %s", phrase, result[0])
        if not confirm and result[0] in ("create", "create_many", "cancel"):
            result = (result[0] + "_direct", result[1])
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
                # #27 : plus de lecture à voix haute à l'échéance (« Alarme : … » insupportable) : son + bandeau
                self._notify(("Alarme : " if x.alarm else "Rappel : ") + x.text)
        if self.timers.tick(t):
            from .timers import spoken
            what = f"Timer de {spoken(self.timers.timer_total)} terminé"
            self.r.active.insert(0, Reminder(text=what, at=now.strftime(FMT), alarm=True))
            self.r.ringing = True
            self._last_ring = t
            if self.sounds is not None:
                self.sounds.play("ALARME")
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
        if kind == "create_direct":
            self.r.add(obj)
            label = "ALARME" if obj.alarm else "RAPPEL"
            core.last_gesture = (f"{label} ENREGISTRE : {describe(obj, now)} : {obj.text}"[:60], t)
            self._say(f"{label.capitalize()} enregistré : {describe(obj, now)}, {obj.text}.")
            return
        if kind == "cancel_direct":
            target = self.r.cancel(obj)
            core.last_gesture = (f"RAPPEL SUPPRIME : {target.text}"[:60] if target else "RAPPEL INTROUVABLE", t)
            return
        if kind == "create_many_direct":
            for r in obj:
                self.r.add(r)
            core.last_gesture = (f"{len(obj)} RAPPELS ENREGISTRES", t)
            self._say(f"{len(obj)} rappels enregistrés.")
            return
        if kind == "create_many":
            self.pending = ("create_many", obj)
            core.ask_confirm("rappel", t, CONFIRM_S)
            core.last_gesture = (f"{len(obj)} RAPPELS : dis ENVOIE pour valider", t)
            self._say(f"{len(obj)} rappels : " + ". ".join(f"{describe(r, now)}, {r.text}" for r in obj)
                      + ". Dis envoie pour valider.")
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
                if what == "create_many":
                    for x in r:
                        self.r.add(x)
                    core.last_gesture = (f"{len(r)} RAPPELS ENREGISTRES", t)
                elif what == "create":
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
                core.last_gesture = ("RAPPEL VALIDE" if done else "AFFICHAGE RETIRE", t)
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
            # en attente d'« envoie » : ce qu'Iris a compris, affiché en haut (il n'y a plus de voix pour le dire)
            "pending": pending_text(self.pending, now),
            "next": None if nxt is None else short_when(nxt, now),   # pour la future vue calendrier
        }
