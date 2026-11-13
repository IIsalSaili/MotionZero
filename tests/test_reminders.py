"""Rappels et alarmes (issue #20) : compréhension, échéances, fichier, voix, île. Sans Haiku ni micro."""
import json
import time
from datetime import datetime, timedelta

import pytest

from motionzero.config import Config
from motionzero.core import Core
from motionzero.reminders import (Desk, Reminder, Reminders, describe, extract_json, next_after, short_when,
                                  validate)
from motionzero.ui import reminder_texts, reminder_view

NOW = datetime(2026, 11, 11, 22, 0)          # un mercredi


def r(at, **kw):
    return Reminder(text=kw.pop("text", "x"), at=at, **kw)


# ---- compréhension de la réponse de Haiku ----
def test_creer_unique():
    kind, rem = validate({"action": "create", "text": "sortir le linge", "at": "2026-11-11T22:20",
                          "repeat": None, "alarm": False}, NOW, set())
    assert kind == "create" and rem.text == "sortir le linge" and rem.at == "2026-11-11T22:20"


def test_creer_repete_et_alarme():
    kind, rem = validate({"action": "create", "text": "médicaments", "at": "2026-11-12T09:00",
                          "repeat": "weekly", "days": [0, 3, "9", "x"], "alarm": True}, NOW, set())
    assert kind == "create" and rem.days == [0, 3] and rem.alarm
    assert rem.at == "2026-11-12T09:00"                       # jeudi 12 : premier jour valable


@pytest.mark.parametrize("data, reason", [
    ({"action": "create", "text": "x", "at": "2026-11-10T09:00", "repeat": None}, "déjà passée"),
    ({"action": "create", "text": "", "at": "2026-11-12T09:00"}, "sans texte"),
    ({"action": "create", "text": "x", "at": "demain"}, "heure incomprise"),
    ({"action": "create", "text": "x", "at": "2026-11-12T09:00", "repeat": "monthly"}, "répétition"),
    ({"action": "create", "text": "x", "at": "2026-11-12T09:00", "repeat": "weekly", "days": []}, "jours"),
    ({"action": "cancel", "id": "zzz"}, "introuvable"),
    ({"action": "error", "reason": "pas de moment"}, "pas de moment"),
    ({"action": "danse"}, "pas compris"),
])
def test_refus(data, reason):
    kind, why = validate(data, NOW, {"abc"})
    assert kind == "error" and reason in why


def test_lister_annuler():
    assert validate({"action": "list"}, NOW, set()) == ("list", None)
    assert validate({"action": "cancel", "id": "abc"}, NOW, {"abc"}) == ("cancel", "abc")


def test_json_dans_du_texte():
    assert extract_json('Voici : {"action": "list"} voilà') == {"action": "list"}
    for bad in ("", "rien", "[1, 2]"):
        with pytest.raises(ValueError):
            extract_json(bad)


# ---- échéances ----
def test_prochaine_echeance():
    daily = r("2026-11-10T09:00", repeat="daily")
    assert next_after(daily, NOW) == datetime(2026, 11, 12, 9, 0)
    week = r("2026-11-13T09:00", repeat="weekdays")             # vendredi
    assert next_after(week, datetime(2026, 11, 13, 10, 0)) == datetime(2026, 11, 16, 9, 0)   # lundi
    weekly = r("2026-11-11T08:00", repeat="weekly", days=[2])
    assert next_after(weekly, NOW) == datetime(2026, 11, 18, 8, 0)
    assert next_after(r("2026-11-11T21:00"), NOW) is None      # unique, passé


def test_descriptions():
    assert describe(r("2026-11-11T23:00"), NOW) == "à 23:00"
    assert describe(r("2026-11-12T09:00"), NOW) == "demain à 09:00"
    assert describe(r("2026-12-03T10:00"), NOW) == "le 03/12 à 10:00"
    assert describe(r("2026-11-12T09:00", repeat="daily"), NOW) == "tous les jours à 09:00"
    assert describe(r("2026-11-12T09:00", repeat="weekly", days=[0]), NOW) == "chaque lundi à 09:00"
    assert short_when(r("2026-11-11T23:00"), NOW) == "23:00"
    assert short_when(r("2026-11-12T09:00"), NOW) == "jeu. 09:00"


def test_declenchement(tmp_path):
    rs = Reminders(str(tmp_path / "r.json"))
    rs.add(r("2026-11-11T22:00", text="unique"))
    rs.add(r("2026-11-11T22:00", text="chaque jour", repeat="daily", alarm=True))
    rs.add(r("2026-11-12T08:00", text="demain"))
    fired = rs.tick(NOW)
    assert [x.text for x in fired] == ["unique", "chaque jour"] and rs.ringing
    assert [x.text for x in rs.items] == ["demain", "chaque jour"]      # le quotidien est reprogrammé
    assert rs.items[1].at == "2026-11-12T22:00"
    assert rs.tick(NOW) == []                                            # pas deux fois


def test_merci_plus_tard_stop(tmp_path):
    rs = Reminders(str(tmp_path / "r.json"))
    rs.add(r("2026-11-11T22:00", text="a", alarm=True))
    rs.add(r("2026-11-11T22:00", text="b"))
    rs.tick(NOW)
    rs.silence()
    assert not rs.ringing and len(rs.active) == 2                        # « stop » : il reste affiché
    assert rs.dismiss().text == "a"
    again = rs.snooze(NOW)
    assert again.text == "b" and again.at == "2026-11-11T22:10" and rs.active == []
    assert rs.dismiss() is None and rs.snooze(NOW) is None               # rien d'affiché : sans planter


def test_fichier_et_rappels_manques(tmp_path):
    path = str(tmp_path / "r.json")
    rs = Reminders(path)
    rs.add(r("2026-11-11T21:00", text="pendant l'absence", alarm=True))
    rs.add(r("2026-11-13T09:00", text="plus tard"))
    back = Reminders(path).load(NOW)
    assert [x.text for x in back.active] == ["pendant l'absence"] and back.active[0].missed
    assert not back.ringing                                              # une alarme manquée ne sonne pas
    assert [x.text for x in back.items] == ["plus tard"]
    assert Reminders(path).load(NOW).active[0].text == "pendant l'absence"   # toujours là après relance


def test_fichier_abime(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{pas du json", encoding="utf-8")
    rs = Reminders(str(path)).load(NOW)
    assert rs.items == [] and rs.load_error and (tmp_path / "r.json.abime").exists()
    assert Reminders(str(tmp_path / "absent.json")).load(NOW).items == []


# ---- chef d'orchestre ----
class FakeSpeaker:
    def __init__(self):
        self.said = []

    def say(self, text, force=False):
        self.said.append(text)


class FakeSounds:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)

    def stop_alarm(self):
        self.played.append("STOP_ALARME")


class FakeBot:
    connected = True

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return 1


def desk(tmp_path, reply=None, text="dans 20 minutes sortir le linge", exc=None, clock=NOW):
    def ask(prompt):
        if exc:
            raise exc
        return json.dumps(reply)
    rs = Reminders(str(tmp_path / "r.json"))
    return Desk(rs, FakeSpeaker(), FakeSounds(), FakeBot(), clock=lambda: clock, ask=ask,
                transcribe=lambda audio: text)


def run(d, core, t=1.0):
    d._work(b"", list(d.r.items))
    d.events(core, t)


def test_creer_puis_envoie(tmp_path):
    d, core = desk(tmp_path, {"action": "create", "text": "sortir le linge", "at": "2026-11-11T22:20"}), Core(Config())
    run(d, core)
    assert core.confirming(2.0) and core.confirm_kind == "rappel"
    assert "sortir le linge" in d.speaker.said[-1]
    assert core.voice("envoie", 3.0) == [("rappel_ok",)]                 # sans « iris »
    d.actions([("rappel_ok",)], core, 3.0)
    assert [x.text for x in d.r.items] == ["sortir le linge"]
    assert d.state(3.0)["next"] == "22:20"


def test_creer_puis_annule(tmp_path):
    d, core = desk(tmp_path, {"action": "create", "text": "x", "at": "2026-11-11T22:20"}), Core(Config())
    run(d, core)
    assert core.voice("annule", 3.0) == [("rappel_non",)]
    d.actions([("rappel_non",)], core, 3.0)
    assert d.r.items == [] and d.pending is None


@pytest.mark.parametrize("kw, expected", [
    ({"text": ""}, "RIEN ENTENDU"),
    ({"exc": RuntimeError("Claude Code introuvable")}, "IRIS INDISPONIBLE"),
    ({"reply": "pas un objet"}, "PAS COMPRIS"),
    ({"reply": {"action": "error", "reason": "pas de moment"}}, "PAS DE MOMENT"),
])
def test_echecs(tmp_path, kw, expected):
    d, core = desk(tmp_path, **kw), Core(Config())
    run(d, core)
    assert expected in core.last_gesture[0] and d.r.items == [] and not core.confirming(2.0)


def test_lister_et_supprimer(tmp_path):
    d, core = desk(tmp_path, {"action": "list"}), Core(Config())
    run(d, core)
    assert core.last_gesture[0] == "AUCUN RAPPEL"
    d.r.add(r("2026-11-12T09:00", text="médicaments", repeat="daily", id="abc"))
    run(d, core, t=5.0)
    assert d.state(6.0)["list"] == ["tous les jours à 09:00 · médicaments"]
    assert d.state(30.0)["list"] is None                                  # disparaît seule
    d._ask = lambda p: json.dumps({"action": "cancel", "id": "abc"})
    run(d, core, t=40.0)
    assert "médicaments" in core.last_gesture[0]
    d.actions([("rappel_ok",)], core, 41.0)
    assert d.r.items == []


def test_echeance_son_voix_discord(tmp_path):
    d, core = desk(tmp_path), Core(Config())
    d.r.add(r("2026-11-11T22:00", text="réveil", alarm=True))
    d.events(core, 10.0)
    assert d.sounds.played[0] == "ALARME" and d.speaker.said[-1] == "Alarme : réveil"
    assert d.bot.sent == [{"t": "notify", "text": "Alarme : réveil"}]
    st = d.state(10.0)["current"]
    assert st["ringing"] and st["text"] == "réveil"
    d.events(core, 12.0)
    assert d.sounds.played.count("ALARME") == 2                           # la sonnerie insiste
    d.actions([("alarm_stop",)], core, 12.5)
    d.events(core, 15.0)
    assert d.sounds.played.count("ALARME") == 2 and d.state(15.0)["current"]   # tait, mais reste affiché
    assert "STOP_ALARME" in d.sounds.played                                  # la boucle audio est arrêtée
    d.actions([("rappel_merci",)], core, 16.0)
    assert d.state(16.0)["current"] is None


def test_bot_absent_rappel_quand_meme(tmp_path):
    d, core = desk(tmp_path), Core(Config())
    d.bot = None
    d.r.add(r("2026-11-11T22:00", text="x"))
    d.events(core, 1.0)
    assert d.state(1.0)["current"]["text"] == "x"


def test_manques_annonces_au_demarrage(tmp_path):
    path = str(tmp_path / "r.json")
    Reminders(path).add(r("2026-11-11T20:00", text="a"))
    d = Desk(Reminders(path).load(NOW), FakeSpeaker(), clock=lambda: NOW)
    d.events(Core(Config()), 1.0)
    assert d.speaker.said == ["1 rappel manqué pendant ton absence."]
    assert d.state(1.0)["current"]["missed"]


# ---- voix ----
def test_mots_de_la_voix():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("rappel", 1.5) == [("open_start",)] and core.open_kind == "rappel"
    assert core.open_tick(10.0, 4.0) == [("rappel_stop",)]               # parlé à 4 s, silence depuis
    core.voice("iris", 20.0)
    assert core.voice("merci", 20.5) == [("rappel_merci",), ("ask_close",)]
    core.voice("iris", 30.0)
    assert core.voice("plus tard", 30.5) == [("rappel_tard",)]
    assert ("alarm_stop",) in core.voice("stop", 40.0)                    # « stop » seul : toujours
    assert core.voice("merci", 50.0) == []                                # sans « iris » : ignoré


def test_plus_tard_entendu_en_deux_mots():
    from motionzero.voice import _join_demute
    words = [{"word": "plus", "conf": 1, "start": 0, "end": 1}, {"word": "tard", "conf": 1, "start": 1, "end": 2}]
    assert _join_demute(words)[0]["word"] == "plus tard"


# ---- île ----
def test_vue_de_l_ile():
    assert reminder_view({}) is None
    cur = {"text": "réveil", "alarm": True, "ringing": True, "missed": False, "more": 1, "when": "07:00"}
    st = {"reminders": {"current": cur, "list": ["a"]}}
    assert reminder_view(st) == ("current", cur)                          # le rappel passe avant la liste
    title, body, meta = reminder_texts("current", cur)
    assert title == "ALARME · 07:00 · +1 en attente" and body == "réveil"
    assert "stop" in meta and "Iris merci" in meta
    assert reminder_texts("list", ["a", "b"])[1] == "a\nb"
    assert reminder_texts("current", {**cur, "alarm": False, "missed": True})[0].startswith("RAPPEL MANQUÉ")


# ---- plusieurs horaires par jour ----
POIGNETS = {"action": "create", "text": "travailler mes poignets", "at": "2026-11-12T12:00", "repeat": "daily",
            "times": ["12:00", "14:00", "16:00", "18:00", "20:00", "22:00"]}


def test_toutes_les_2_heures_a_partir_de_midi():
    kind, rem = validate(POIGNETS, datetime(2026, 11, 12, 13, 5), set())
    assert kind == "create" and rem.at == "2026-11-12T14:00"            # midi passé : 14 h
    assert describe(rem, datetime(2026, 11, 12, 13, 5)) == "tous les jours toutes les 2 h de 12:00 à 22:00"
    assert next_after(rem, datetime(2026, 11, 12, 22, 30)) == datetime(2026, 11, 13, 12, 0)   # lendemain midi


def test_horaires_qui_s_enchainent(tmp_path):
    rs = Reminders(str(tmp_path / "r.json"))
    kind, rem = validate(POIGNETS, datetime(2026, 11, 12, 11, 0), set())
    rs.add(rem)
    seen = []
    for h in (12, 14, 16, 18, 20, 22):
        fired = rs.tick(datetime(2026, 11, 12, h, 0))
        seen += [x.text for x in fired]
        rs.dismiss()
    assert len(seen) == 6 and rs.items[0].at == "2026-11-13T12:00"


def test_horaires_irreguliers_et_un_seul_jour():
    kind, rem = validate({"action": "create", "text": "x", "at": "2026-11-12T09:00", "repeat": "weekdays",
                          "times": ["21:00", "09:00", "09:00"]}, NOW, set())
    assert rem.times == ["09:00", "21:00"] and describe(rem, NOW) == "en semaine à 09:00 et 21:00"
    kind, today = validate({"action": "create", "text": "x", "at": "2026-11-11T22:30", "repeat": None,
                            "times": ["22:30", "23:30"]}, NOW, set())
    assert next_after(today, datetime(2026, 11, 11, 23, 0)) == datetime(2026, 11, 11, 23, 30)
    assert next_after(today, datetime(2026, 11, 11, 23, 45)) is None    # pas répété : fini ce soir


@pytest.mark.parametrize("times, why", [(["midi"], "horaires incompris"),
                                        ([f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 20, 40)], "trop")])
def test_horaires_refuses(times, why):
    assert why in validate({**POIGNETS, "times": times}, NOW, set())[1]


# ---- « iris heure / date » ----
def test_iris_heure_et_date():
    from motionzero.ui import clock_text
    core = Core(Config())
    assert clock_text(datetime(2026, 11, 12, 14, 5)) == "jeudi 12/11/2026 · 14:05"
    core.voice("iris", 1.0)
    assert core.voice("heure", 1.5) == [] and core.clock_until == 1.5 + Config().clock_s
    core.voice("iris", 20.0)
    core.voice("date", 20.5)
    assert core.clock_until == 20.5 + Config().clock_s
    assert core.voice("heure", 40.0) == [] and core.clock_until == 20.5 + Config().clock_s   # sans « iris »


def test_animation_du_logo():
    from motionzero.ui import CLOCK_ANIM_S, clock_anim
    assert clock_anim(1.0, None, None) == (0.0, 0.0)                      # au repos
    k, a = clock_anim(0.0, 0.0, None)
    assert k == 0.0 and a == 0.0
    k, a = clock_anim(CLOCK_ANIM_S / 2, 0.0, None)
    assert 0 < k < 1 and a < 0                                            # aller : tourne à gauche
    assert clock_anim(3.0, 0.0, None) == (1.0, -360.0)                    # pleine taille
    k, a = clock_anim(5.0 + CLOCK_ANIM_S / 2, 0.0, 5.0)
    assert 0 < k < 1 and a > 0                                            # retour : tourne à droite
    assert clock_anim(5.0 + CLOCK_ANIM_S, 0.0, 5.0) == (0.0, 360.0)       # revenu


def test_rappel_en_attente_affiche_en_haut():
    """Plus de voix : le rappel compris doit s'afficher dans l'île pendant « dis ENVOIE »."""
    from datetime import datetime
    from motionzero.reminders import Reminder, pending_text
    from motionzero.ui import island_text
    now = datetime(2026, 11, 13, 12, 0)
    assert pending_text(None, now) is None
    r = Reminder(text="appeler maman", at="2026-11-14T18:30")
    txt = pending_text(("create", r), now)
    assert txt == "Rappel · demain à 18:30 · appeler maman"
    assert pending_text(("create", Reminder(text="pâtes", at="2026-11-13T19:00")), now) == \
        "Rappel · aujourd'hui à 19:00 · pâtes"
    assert pending_text(("cancel", r), now).startswith("Supprimer · ")
    st = {"confirming": True, "reminders": {"pending": txt}}
    assert island_text(st)[1] == txt + " — dis ENVOIE"
    assert island_text({"confirming": True})[1] == "Dis ENVOIE ou ANNULE"   # dictée Claude : inchangé



def test_ok_et_okay_comme_merci():
    from motionzero.config import Config
    from motionzero.core import Core
    for mot in ("ok", "okay"):
        core = Core(Config())
        core.voice("iris", 1.0)
        assert core.voice(mot, 1.2) == [("rappel_merci",), ("ask_close",)]


def test_merci_retire_l_heure():
    from motionzero.config import Config
    from motionzero.core import Core
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("heure", 1.2)
    assert core.clock_until > 2.0
    core.voice("iris", 2.0)
    core.voice("ok", 2.2)
    assert core.clock_until < 0


def test_serie_dans_chrome_ok_ne_ferme_pas_l_onglet():
    """Le conflit du 13/11 : en mode Chrome, retirer l'affichage ne doit jamais fermer l'onglet."""
    from motionzero.config import Config
    from motionzero.core import Core, Mode
    core = Core(Config())
    core.mode = Mode.CHROME
    core.voice("iris", 1.0)
    acts = core.voice("ok", 1.2)
    assert ("chrome_keys", ["ctrl", "w"]) not in acts and ("ask_close",) in acts
    core.voice("iris", 2.0)
    acts = core.voice("ferme", 2.2)
    assert ("chrome_keys", ["ctrl", "w"]) in acts and ("ask_close",) not in acts and ("rappel_merci",) not in acts


def test_ok_sans_iris_ignore():
    from motionzero.config import Config
    from motionzero.core import Core
    assert Core(Config()).voice("ok", 1.0) == []
