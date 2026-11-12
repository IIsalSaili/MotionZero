"""« iris chronomètre » / « iris timer » : durées dites, compte, sonnerie, annulation. Sans micro ni écran."""
from datetime import datetime

import pytest

from motionzero.config import Config
from motionzero.core import Core
from motionzero.reminders import Desk, Reminders
from motionzero.timers import Timers, fmt, parse_duration, spoken

NOW = datetime(2026, 11, 12, 15, 30)


@pytest.mark.parametrize("said, seconds", [
    ("Cinq minutes.", 300), ("5min", 300), ("1 h 30", 5400), ("1h30", 5400), ("Une heure et demie", 5400),
    ("une heure et quart", 4500), ("une demi-heure", 1800), ("un quart d'heure", 900), ("90 secondes", 90),
    ("2 min 30", 150), ("Vingt-cinq minutes", 1500), ("quarante-cinq secondes", 45), ("10", 600),
    ("3 heures", 10800), ("Dix minutes et trente secondes", 630), ("vingt et une minutes", 1260),
])
def test_durees(said, seconds):
    assert parse_duration(said) == seconds


@pytest.mark.parametrize("said", ["", "rien", "0 minute", "25 heures", "bonjour Iris"])
def test_durees_refusees(said):
    assert parse_duration(said) is None


def test_affichage():
    assert fmt(300) == "05:00" and fmt(299.2) == "05:00" and fmt(3725) == "1:02:05" and fmt(-3) == "00:00"
    assert spoken(5400) == "1 heure 30 minutes" and spoken(45) == "45 secondes" and spoken(7201) == "2 heures 1 seconde"


def test_chrono():
    tm = Timers()
    assert tm.toggle_chrono(10.0) is None
    assert tm.state(75.5)["chrono"] == {"text": "01:05", "done": False}
    assert tm.toggle_chrono(80.0) == 70.0
    assert tm.state(85.0)["chrono"] == {"text": "01:10", "done": True}
    assert tm.state(95.0)["chrono"] is None                              # disparaît 10 s après l'arrêt


def test_timer():
    tm = Timers()
    tm.start_timer(0.0, 300)
    assert tm.state(0.0)["timer"] == {"text": "05:00"} and tm.state(299.5)["timer"] == {"text": "00:01"}
    assert not tm.tick(299.0) and tm.tick(300.0) and not tm.tick(301.0)  # sonne une seule fois
    assert tm.state(301.0)["timer"] is None
    tm.start_timer(0.0, 60)
    assert tm.cancel_timer() and not tm.cancel_timer() and not tm.tick(100.0)


# ---- voix ----
def test_voix_chrono_et_timer():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("chronomètre", 1.5) == [("chrono",)]
    core.voice("iris", 3.0)
    assert core.voice("timer", 3.5) == [("open_start",)] and core.open_kind == "timer"
    assert core.open_tick(10.0, 5.0) == [("timer_stop",)]
    core.timer_running = True
    core.voice("iris", 20.0)
    assert core.voice("timer", 20.5) == [("timer_cancel",)]              # redit pendant qu'il tourne : annulé
    assert core.voice("chronomètre", 40.0) == []                         # sans « iris » : ignoré


def test_timer_rien_dit():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("timer", 1.5)
    assert core.open_tick(30.0, 0.0) == [("open_cancel",)]
    assert core.last_gesture[0] == "RIEN ENTENDU : timer annule"


# ---- avec le Desk ----
class Spk:
    def __init__(self):
        self.said = []

    def say(self, text, force=False):
        self.said.append(text)


class Snd:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


class Bot:
    connected = True

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return 1


def desk(tmp_path, said="cinq minutes", exc=None):
    def transcribe(audio):
        if exc:
            raise exc
        return said
    return Desk(Reminders(str(tmp_path / "r.json")), Spk(), Snd(), Bot(), clock=lambda: NOW, transcribe=transcribe)


def test_timer_complet(tmp_path):
    d, core = desk(tmp_path), Core(Config())
    d._work_timer(b"")
    d.events(core, 100.0)
    assert core.timer_running and d.state(100.0)["timers"]["timer"] == {"text": "05:00"}
    assert d.speaker.said[-1] == "Timer de 5 minutes."
    d.events(core, 400.0)                                                # zéro : alarme
    cur = d.state(400.0)["current"]
    assert cur["text"] == "Timer de 5 minutes terminé" and cur["ringing"] and not core.timer_running
    assert "ALARME" in d.sounds.played and d.bot.sent[-1]["t"] == "notify"
    d.actions([("alarm_stop",)], core, 401.0)
    d.actions([("rappel_merci",)], core, 402.0)
    assert d.state(402.0)["current"] is None


@pytest.mark.parametrize("kw, expected", [({"said": ""}, "RIEN ENTENDU"), ({"said": "bonjour"}, "DUREE INCOMPRISE"),
                                          ({"exc": RuntimeError("gpu")}, "RIEN ENTENDU")])
def test_timer_echecs(tmp_path, kw, expected):
    d, core = desk(tmp_path, **kw), Core(Config())
    d._work_timer(b"")
    d.events(core, 1.0)
    assert expected in core.last_gesture[0] and d.state(1.0)["timers"]["timer"] is None


def test_chrono_desk_et_annulation_timer(tmp_path):
    d, core = desk(tmp_path), Core(Config())
    d.actions([("chrono",)], core, 10.0)
    assert d.state(70.0)["timers"]["chrono"]["text"] == "01:00"
    d.actions([("chrono",)], core, 70.0)
    assert d.speaker.said[-1] == "1 minute." and core.last_gesture[0] == "CHRONOMETRE ARRETE"
    d._work_timer(b"")
    d.events(core, 100.0)
    d.actions([("timer_cancel",)], core, 110.0)
    d.events(core, 500.0)
    assert d.state(500.0)["current"] is None and not core.timer_running  # annulé : ne sonne pas


def test_ile_fiches(tmp_path):
    from motionzero.ui import QApplication, _IslandPainter
    QApplication.instance() or QApplication([])
    p = _IslandPainter(1400)
    st = {"mode": "NEUTRE", "reminders": {"timers": {"chrono": {"text": "01:05", "done": False}, "timer": {"text": "04:59"}}}}
    p.update(st, 1.0)
    assert p.timer_pills == [("Chrono 01:05", False), ("Timer 04:59", True)]
    p.update({"mode": "NEUTRE"}, 2.0)
    assert p.timer_pills == []
