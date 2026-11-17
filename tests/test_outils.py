"""Outils ajoutés à « iris instruction » (#45) : routines, favoris, navigateur, fenêtres, infos ; échecs compris."""
import datetime
import json
import sqlite3

import pytest

from motionzero import outils as o
from motionzero.instruction import TOOLS, PlanError, check_plan, check_plan_raw, check_step, expand


# ---- garantie : aucun mot de plus écouté en permanence
def test_aucun_nouveau_mot_guette():
    """Les outils passent tous par « iris instruction » puis Whisper (texte libre) : la liste des mots que Vosk
    guette en permanence ne grandit pas. Nombres figés le 17/11 (« instruction » compris) : un ajout doit être
    voulu et ce test mis à jour à la main."""
    from motionzero.voice import GRAMMARS, WORDS
    assert len(WORDS) == 125
    assert {k: len(json.loads(v)) for k, v in GRAMMARS.items()} == \
        {"base": 75, "souris": 75, "chrome": 86, "calendrier": 127}
    for g in GRAMMARS.values():
        assert not [t for t in TOOLS if t in json.loads(g) and "_" in t]


# ---- magasins
def test_store_garde_et_oublie(tmp_path):
    p = tmp_path / "favoris.json"
    s = o.Store(str(p))
    s.put("Mes Mails", "https://mail.google.com")
    assert o.Store(str(p)).get("mes mails") == "https://mail.google.com"
    assert s.remove("MES MAILS") and not s.remove("inconnu")


def test_store_fichier_abime_repart_vide(tmp_path):
    p = tmp_path / "routines.json"
    p.write_text("{pas du json", encoding="utf-8")
    assert o.Store(str(p)).names() == []


# ---- routines
def test_creer_routine_n_execute_rien_et_retient(tmp_path):
    routines = o.Store(str(tmp_path / "r.json"))
    raw = {"etapes": [{"outil": "cree_routine", "arg": "mode travail"},
                      {"outil": "discord", "arg": "coupe"}, {"outil": "volume", "arg": "30"}], "refus": ""}
    plan = check_plan(raw, ctx={"routines": routines})
    assert len(plan) == 1 and plan[0][0] == "cree_routine" and "mode travail" in plan[0][2]
    name, steps = plan[0][1]
    assert [s["outil"] for s in steps] == ["discord", "volume"]


def test_routine_interdite_refusee_a_la_creation():
    raw = {"etapes": [{"outil": "cree_routine", "arg": "x"}, {"outil": "touche", "arg": "win+x"}], "refus": ""}
    with pytest.raises(PlanError, match="interdit"):
        check_plan(raw)
    with pytest.raises(PlanError):
        check_plan({"etapes": [{"outil": "cree_routine", "arg": "x"}, {"outil": "routine", "arg": "y"}], "refus": ""})


def test_lancer_routine_et_refais(tmp_path):
    routines = o.Store(str(tmp_path / "r.json"))
    routines.put("mode pause", [{"outil": "discord", "arg": "coupe"}, {"outil": "video", "arg": "pause"}])
    plan, flat = check_plan_raw({"etapes": [{"outil": "routine", "arg": "Mode Pause"}], "refus": ""},
                                ctx={"routines": routines})
    assert [p[0] for p in plan] == ["discord", "video"]
    again = check_plan({"etapes": [{"outil": "refais", "arg": ""}], "refus": ""}, ctx={"last": flat})
    assert [p[0] for p in again] == ["discord", "video"]
    with pytest.raises(PlanError, match="inconnue"):
        check_plan({"etapes": [{"outil": "routine", "arg": "nope"}], "refus": ""}, ctx={"routines": routines})
    with pytest.raises(PlanError, match="refaire"):
        check_plan({"etapes": [{"outil": "refais", "arg": ""}], "refus": ""})


def test_routine_trafiquee_revérifiee(tmp_path):
    routines = o.Store(str(tmp_path / "r.json"))
    routines.put("piege", [{"outil": "touche", "arg": "alt+f4"}])     # fichier modifié à la main
    with pytest.raises(PlanError, match="interdit"):
        check_plan({"etapes": [{"outil": "routine", "arg": "piege"}], "refus": ""}, ctx={"routines": routines})
    assert expand([{"outil": "routine", "arg": "piege"}], routines)[0]["outil"] == "touche"


# ---- favoris
def test_favoris(tmp_path):
    favs = o.Store(str(tmp_path / "f.json"))
    _, (name, url), _ = check_step("ajoute_favori", "mes mails = mail.google.com", ctx={"favoris": favs})
    assert url == "https://mail.google.com"
    favs.put(name, url)
    assert check_step("favori", "Mes mails", ctx={"favoris": favs})[1] == url
    for bad in ("inconnu",):
        with pytest.raises(PlanError):
            check_step("favori", bad, ctx={"favoris": favs})
    with pytest.raises(PlanError):
        check_step("ajoute_favori", "sans adresse", ctx={"favoris": favs})
    with pytest.raises(PlanError):
        check_step("ajoute_favori", "local = file:///C:/Users", ctx={"favoris": favs})


# ---- navigateur
def test_recherche_ciblee():
    assert o.search_url("amazon: casque audio") == "https://www.amazon.fr/s?k=casque+audio"
    assert "maps/dir" in o.search_url("itinéraire: Gare de Lyon")
    assert o.search_url("darkweb: x") is None and o.search_url("pas de site") is None
    with pytest.raises(PlanError):
        check_step("recherche", "inconnu: x")


def test_video_et_musique():
    assert check_step("video", "plein écran")[1] == ["f"]
    assert check_step("video", "suivante")[1] == ["shift", "n"]
    assert check_step("musique", "suivant")[1] == 0xB0
    with pytest.raises(PlanError):
        check_step("video", "supprime")
    with pytest.raises(PlanError):
        check_step("musique", "éteins")


def test_onglet_trouve_et_tour_complet():
    titles = ["Gmail - Google Chrome", "One Click Studio - YouTube - Google Chrome", "Docs - Google Chrome"]
    i = {"n": 0}
    assert o.find_tab("youtube", title=lambda: titles[i["n"] % 3],
                      next_tab=lambda: i.__setitem__("n", i["n"] + 1), pause=0)
    i["n"] = 0
    assert not o.find_tab("netflix", title=lambda: titles[i["n"] % 3],
                          next_tab=lambda: i.__setitem__("n", i["n"] + 1), pause=0)
    assert i["n"] <= 4                        # s'arrête après un tour


def test_historique_lu_sans_toucher_l_original(tmp_path):
    db = tmp_path / "History"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE urls (title TEXT, url TEXT, last_visit_time INTEGER)")
    con.executemany("INSERT INTO urls VALUES (?,?,?)", [
        ("Accueil", "https://www.youtube.com/", 3),
        ("Raccourcis clavier - One Click Studio", "https://www.youtube.com/watch?v=D93YJMy5fPE", 2),
        ("One Click Studio - article", "https://blog.example/oneclick", 4)])
    con.commit()
    con.close()
    before = db.read_bytes()
    rows = o.read_history(str(db))
    assert db.read_bytes() == before
    assert o.pick_history(rows, "one click studio", video=True).endswith("D93YJMy5fPE")
    assert o.pick_history(rows, "one click studio") == "https://blog.example/oneclick"
    assert o.pick_history(rows, "netflix") is None


# ---- fenêtres
def test_fenetre_et_devant_verifies():
    apps = {"Discord": "x", "Google Chrome": "y", "Paramètres": "z"}
    assert check_step("fenetre", "chrome: gauche", apps)[1] == ("Google Chrome", "gauche")
    assert check_step("devant", "discord", apps)[1] == "Discord"
    with pytest.raises(PlanError):
        check_step("fenetre", "chrome: en haut", apps)
    with pytest.raises(PlanError, match="interdit"):
        check_step("devant", "paramètres", apps)


# ---- infos
@pytest.mark.parametrize("expr,res", [("15 % de 240", "36"), ("2 + 3 x 4", "14"), ("racine de 81", "9"),
                                      ("10 divisé par 4", "2,5")])
def test_calcul(expr, res):
    assert o.calc(expr).endswith("= " + res)


@pytest.mark.parametrize("expr", ["__import__('os')", "9 ** 99999", "1 / 0", "ouvre"])
def test_calcul_refuse(expr):
    with pytest.raises((ValueError, ZeroDivisionError, SyntaxError)):
        o.calc(expr)


def test_conversions():
    assert o.convert("5 miles en km").endswith("8,047 km")
    assert o.convert("100 °F en °C").startswith("100 °F = 37,8")
    with pytest.raises(ValueError):
        o.convert("3 km en kg")
    get = lambda url: {"rates": {"USD": 1.1}}
    assert o.money("20 euros en dollars", get) == "20 EUR = 22 USD"
    with pytest.raises(ValueError):
        o.money("20 bananes en dollars", get)


def test_heure_et_meteo():
    now = datetime.datetime(2026, 11, 17, 12, 0, tzinfo=datetime.timezone.utc)
    assert o.time_in("Tokyo", now) == "Tokyo : 21:00"
    with pytest.raises(ValueError):
        o.time_in("Atlantide", now)
    pages = {"geocoding": {"results": [{"name": "Paris", "latitude": 48.8, "longitude": 2.3}]},
             "forecast": {"current": {"temperature_2m": 11.6, "weather_code": 61},
                          "daily": {"temperature_2m_min": [7], "temperature_2m_max": [13],
                                    "precipitation_probability_max": [80]}}}
    get = lambda url: next(v for k, v in pages.items() if k in url)
    assert o.weather("Paris", get) == "Paris : 12 °C, pluie faible (min 7, max 13, pluie 80 %)"
    with pytest.raises(RuntimeError):
        o.weather("Nullepart", lambda url: {"results": []})
