"""« Iris calendrier » (#21) : semaine, ruban du mois, jour en grand, commandes vocales. Sans écran ni micro."""
import json
from datetime import date, datetime

from motionzero.calendar_view import WORDS, Calendar, day_cards, day_detail, occurrences
from motionzero.config import Config
from motionzero.core import Core
from motionzero.reminders import Desk, Reminder, Reminders
from motionzero.ui import reminder_view

NOW = datetime(2026, 11, 12, 15, 30)        # jeudi
TODAY = NOW.date()
ITEMS = [
    Reminder("réveil", "2026-11-13T07:30", repeat="weekdays", alarm=True),
    Reminder("poignets", "2026-11-12T16:00", repeat="daily", times=["12:00", "14:00", "16:00", "18:00", "20:00", "22:00"]),
    Reminder("kiné", "2026-11-12T17:00"),
    Reminder("train", "2026-11-21T09:30", alarm=True),
] + [Reminder(f"rdv {h}", f"2026-11-14T{h}:00") for h in (10, 11, 12, 20)]


def test_occurrences():
    reveil, poignets, kine = ITEMS[0], ITEMS[1], ITEMS[2]
    assert occurrences(reveil, date(2026, 11, 13)) == ["07:30"]
    assert occurrences(reveil, date(2026, 11, 14)) == []                 # samedi
    assert occurrences(reveil, date(2026, 11, 12)) == []                 # avant sa prochaine échéance
    assert len(occurrences(poignets, date(2026, 11, 20))) == 6
    assert occurrences(kine, TODAY) == ["17:00"] and occurrences(kine, date(2026, 11, 13)) == []


def test_cartes_du_jour():
    events, routine = day_cards(ITEMS, date(2026, 11, 13))
    assert events == [] and routine == ["07:30 réveil", "poignets × 6\n12:00 → 22:00"]
    events, _ = day_cards(ITEMS, TODAY)
    assert events == [{"t": "17:00", "txt": "Kiné", "alarm": False}]
    assert [e["t"] for e in day_detail(ITEMS, date(2026, 11, 14))][:3] == ["10:00", "11:00", "12:00"]


def test_vue_semaine_ruban_et_plus():
    cal = Calendar()
    cal.show(TODAY)
    v = cal.view(ITEMS, NOW)
    assert v["title"] == "9 → 15 novembre" and v["month"] == "Novembre 2026"
    assert [d["n"] for d in v["days"]] == list(range(9, 16))
    sat = v["days"][5]
    assert len(sat["items"]) == 3 and sat["more"] == 1                  # 4 rendez-vous : « + 1 autre »
    thu = v["days"][3]
    assert thu["today"] and thu["focus"] and not thu["past"] and v["days"][0]["past"]
    strip = {s["n"]: s for s in v["strip"]}
    assert len(strip) == 30 and strip[21]["kind"] == "a" and strip[12]["kind"] == "r"
    assert strip[13]["kind"] is None                                     # le réveil répété ne colore pas
    assert strip[12]["today"] and strip[9]["week"] and not strip[16]["week"]


def test_commandes():
    cal = Calendar()
    cal.show(TODAY)
    assert cal.command("suivant", TODAY) and cal.week == date(2026, 11, 16)
    cal.command("précédent", TODAY)
    cal.command("précédent", TODAY)
    assert cal.week == date(2026, 11, 2)
    cal.command("aujourd'hui", TODAY)
    assert cal.week == date(2026, 11, 9) and cal.focus == TODAY
    cal.command("dix-huit", TODAY)
    assert cal.week == date(2026, 11, 16) and cal.focus == date(2026, 11, 18)
    cal.command("samedi", TODAY)
    assert cal.detail == date(2026, 11, 21)
    assert cal.view(ITEMS, NOW)["detail"]["title"] == "Samedi 21 novembre"
    cal.command("suivant", TODAY)                                        # jour ouvert : jour suivant
    assert cal.detail == date(2026, 11, 22)
    cal.command("suivant", TODAY)
    assert cal.detail == date(2026, 11, 23) and cal.week == date(2026, 11, 23)
    assert cal.command("trente-et-un", TODAY)                            # n'existe pas en novembre : rien
    assert cal.week == date(2026, 11, 23)
    assert not cal.command("banane", TODAY)


def test_changement_de_mois():
    cal = Calendar()
    cal.show(date(2026, 11, 30))
    v = cal.view([], datetime(2026, 11, 30, 9, 0))
    assert v["title"] == "30 novembre → 6 décembre" and v["month"] == "Décembre 2026"
    cal.command("premier", date(2026, 11, 30))
    assert cal.focus == date(2026, 12, 1)
    assert cal.view([], datetime(2026, 11, 30))["days"][0]["items"] == []    # vide : sans planter


# ---- voix ----
def test_ouvrir_naviguer_fermer():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("calendrier", 1.5) == [("cal_open",)]
    assert core.voice("suivant", 3.0) == [("cal", "suivant")]            # sans « iris »
    assert core.voice("dix-huit", 4.0) == [("cal", "dix-huit")]
    core.voice("iris", 5.0)
    assert core.voice("jeudi", 5.5) == [("cal", "jeudi")]               # avec « iris » aussi
    assert core.voice("ferme", 6.0) == []                                # « ferme » ne touche plus à l'affichage
    assert core.voice("merci", 6.2) == [("cal_close",)]                  # « merci » / « ok » le ferment
    assert core.voice("suivant", 7.0) == []                              # fermé : plus rien


def test_mots_du_calendrier_ignores_sans_bruit():
    core = Core(Config())
    core.last_gesture = ("AVANT", 0.0)
    assert core.voice("dix-huit", 1.0) == [] and core.last_gesture == ("AVANT", 0.0)


def test_fermeture_par_stop_merci_et_inactivite():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("calendrier", 1.5)
    assert ("cal_close",) in core.voice("stop", 2.0)
    core.voice("iris", 3.0)
    core.voice("calendrier", 3.5)
    assert core.voice("merci", 4.0) == [("cal_close",)]
    core.voice("iris", 5.0)
    core.voice("calendrier", 5.5)
    assert core.voice("suivant", 5.5 + 61) == []                         # une minute sans rien : fermé


def test_desk_et_ile(tmp_path):
    rs = Reminders(str(tmp_path / "r.json"))
    rs.add(Reminder("kiné", "2026-11-12T17:00"))
    d = Desk(rs, clock=lambda: NOW)
    core = Core(Config())
    assert d.state(1.0)["calendar"] is None
    d.actions([("cal_open",)], core, 1.0)
    cal = d.state(1.0)["calendar"]
    assert cal["days"][3]["items"][0]["txt"] == "Kiné"
    assert reminder_view({"reminders": d.state(1.0)})[0] == "calendar"
    d.actions([("cal", "suivant")], core, 2.0)
    assert d.state(2.0)["calendar"]["title"] == "16 → 22 novembre"
    assert d.state(3.0, calendar_open=False)["calendar"] is None        # fermé par inactivité
    d.actions([("cal", "lundi")], core, 4.0)                             # mot reçu fermé : rouvre
    assert d.state(4.0)["calendar"]["detail"]["title"] == "Lundi 9 novembre"
    d.actions([("cal_close",)], core, 5.0)
    assert d.state(5.0)["calendar"] is None


def test_un_rappel_qui_sonne_passe_avant_le_calendrier():
    st = {"reminders": {"current": {"text": "x"}, "calendar": {"days": []}}}
    assert reminder_view(st)[0] == "current"


def test_mots_dans_la_grammaire():
    from motionzero.voice import GRAMMAR
    words = json.loads(GRAMMAR)
    assert all(w in words for w in WORDS) and "calendrier" in words


# ---- mois précisés ----
def test_annee_la_plus_proche():
    from motionzero.calendar_view import nearest_date
    assert nearest_date(TODAY, 1, 1) == date(2027, 1, 1)                 # en novembre : janvier prochain
    assert nearest_date(TODAY, 11, 1) == date(2026, 11, 1)               # il y a 11 jours : cette année
    assert nearest_date(TODAY, 9, 1) == date(2026, 9, 1)                 # il y a 72 jours : encore récent
    assert nearest_date(TODAY, 5, 14) == date(2027, 5, 14)               # il y a 6 mois : le prochain
    assert nearest_date(TODAY, 11, 12) == TODAY
    assert nearest_date(date(2027, 1, 3), 12, 25) == date(2026, 12, 25)  # début janvier : Noël récent
    assert nearest_date(TODAY, 2, 30) is None
    assert nearest_date(TODAY, 2, 29) == date(2028, 2, 29)               # prochaine année bissextile


def test_premier_janvier():
    cal = Calendar()
    cal.show(TODAY)
    cal.command("premier", TODAY, t=10.0)
    cal.command("janvier", TODAY, t=10.4)
    assert cal.focus == date(2027, 1, 1) and cal.week == date(2026, 12, 28)
    assert cal.view([], NOW)["month"] == "Décembre 2026"                  # semaine à cheval : mois du jeudi
    cal.command("deuxième", TODAY, t=20.0)
    cal.command("mars", TODAY, t=20.5)
    assert cal.focus == date(2027, 3, 2)
    cal.command("dix-huit", TODAY, t=30.0)
    cal.command("février", TODAY, t=40.0)                                # trop tard : mois seul = le 1er
    assert cal.focus == date(2027, 2, 1)
    cal.command("trente", TODAY, t=50.0)                                 # 30 du mois affiché (février : rien)
    before = cal.focus
    cal.command("février", TODAY, t=50.2)                                # « trente février » : ne bouge pas
    assert cal.focus == before


def test_voix_premier_janvier():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("calendrier", 1.5)
    assert core.voice("premier", 3.0) == [("cal", "premier")]
    assert core.voice("janvier", 3.3) == [("cal", "janvier")]
    assert core.voice("janvier", 200.0) == []                            # calendrier fermé : rien
