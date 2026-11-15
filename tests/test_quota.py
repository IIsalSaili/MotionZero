"""« iris quota » : quota Claude de la session de 5 h, en haut à droite, allumé / éteint à la voix."""
import datetime
import json
import urllib.error

from motionzero import aide, quota
from motionzero.config import Config
from motionzero.core import Core
from motionzero.voice import WORDS

TZ = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 11, 15, 18, 30, tzinfo=TZ)
SAMPLE = {"five_hour": {"utilization": 40.0, "resets_at": "2026-11-15T21:59:59.616110+00:00"},
          "seven_day": {"utilization": 53.0, "resets_at": "2026-11-19T21:59:59+00:00"}}


def say(core, word, t=1.0):
    core.voice("iris", t)
    return core.voice(word, t + 0.3)


def test_texte_pourcentage_utilise_et_heure_du_reset():
    pct, reset = quota.parse(SAMPLE)
    assert quota.quota_text(pct, reset.astimezone(TZ), NOW) == "40 % · reset 22h59"


def test_reset_demain_ou_plus_tard_precise():
    demain = datetime.datetime(2026, 11, 16, 1, 5, tzinfo=TZ)
    assert quota.quota_text(12.4, demain, NOW) == "12 % · reset demain 1h05"
    loin = datetime.datetime(2026, 11, 18, 9, 0, tzinfo=TZ)
    assert quota.quota_text(12, loin, NOW) == "12 % · reset 18/11 9h00"


def test_pas_de_session_en_cours():
    pct, reset = quota.parse({"five_hour": {"utilization": 0, "resets_at": None}})
    assert quota.quota_text(pct, reset, NOW) == "0 % · pas de session"


def test_format_change_donne_valueerror():
    for bad in ({}, {"five_hour": None}, {"five_hour": {"utilization": "x"}}):
        try:
            quota.parse(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def _fail(exc):
    def f(*a):
        raise exc
    return f


def test_echecs_affichent_indisponible_sans_planter():
    for q in (quota.Quota(token_reader=_fail(FileNotFoundError("pas de .credentials.json")), fetcher=lambda t: SAMPLE),
              quota.Quota(token_reader=lambda: "x", fetcher=_fail(urllib.error.URLError("pas de réseau"))),
              quota.Quota(token_reader=lambda: "x", fetcher=_fail(urllib.error.HTTPError(quota.URL, 401, "", None, None))),
              quota.Quota(token_reader=lambda: "x", fetcher=lambda t: {"autre": 1}),
              quota.Quota(token_reader=lambda: "x", fetcher=_fail(json.JSONDecodeError("x", "", 0)))):
        assert q.refresh_now() is False
        assert q.text(NOW) == "Quota indisponible"


def test_reussite_puis_echec_n_affiche_pas_de_vieux_chiffre():
    answers = [SAMPLE, None]
    def fetch(t):
        a = answers.pop(0)
        if a is None:
            raise urllib.error.URLError("coupé")
        return a
    q = quota.Quota(token_reader=lambda: "x", fetcher=fetch)
    assert q.text(NOW) == "Quota…"            # avant la première lecture
    assert q.refresh_now() and q.text(NOW).startswith("40 %")
    assert not q.refresh_now() and q.text(NOW) == "Quota indisponible"


def test_tick_lit_en_fond_seulement_si_affiche_et_a_l_heure():
    calls = []
    q = quota.Quota(token_reader=lambda: "x", fetcher=lambda t: calls.append(1) or SAMPLE)
    q.tick(0.0, shown=False)
    assert calls == []
    q.tick(0.0, shown=True)
    for th in __import__("threading").enumerate():
        if th.name == "quota":
            th.join(2)
    assert calls == [1]
    q.tick(10.0, shown=True)                  # 5 min pas écoulées : rien
    assert calls == [1]
    q.force()
    q.tick(11.0, shown=True)
    for th in __import__("threading").enumerate():
        if th.name == "quota":
            th.join(2)
    assert calls == [1, 1]


def test_iris_quota_bascule():
    core = Core(Config())
    assert core.quota_shown is False
    assert ("quota", True) in say(core, "quota", 1.0)
    assert core.quota_shown
    assert ("quota", False) in say(core, "quota", 5.0)
    assert not core.quota_shown


def test_mot_connu_de_la_voix_et_de_l_aide():
    assert "quota" in WORDS
    assert any("quota" in mot for _, lignes in aide.GROUPS for mot, _ in lignes)


def test_choix_garde(tmp_path):
    p = str(tmp_path / "quota.txt")
    assert quota.read_shown(p) is False        # fichier absent : masqué
    quota.write_shown(p, True)
    assert quota.read_shown(p) is True
    quota.write_shown(p, False)
    assert quota.read_shown(p) is False
    quota.write_shown(str(tmp_path / "absent" / "q.txt"), True)   # écriture impossible : pas d'exception
