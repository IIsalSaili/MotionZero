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
    # 17/11 : 7 mots passés dans « instruction », « bypass » ajouté ; puis « candidature » (+1 partout). Les mots
    # du mode candidature (cherche, état, offres) ne sont guettés que mode allumé.
    assert len(WORDS) == 117   # « espace », « muet », « activation », « favori » retirés (#50)
    assert {k: len(json.loads(v)) for k, v in GRAMMARS.items()} == \
        {"base": 67, "souris": 67, "chrome": 75, "calendrier": 119, "candidature": 31, "candidature_souris": 37}   # 21/11 : annule, détails, vérifie, relances
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


# ---- sites : par leur nom, sans rien enregistrer avant
def test_site_connu_d_office_ou_retenu(tmp_path):
    favs = o.Store(str(tmp_path / "f.json"))
    assert check_step("site", "mes mails", ctx={"favoris": favs})[1] == "https://mail.google.com"
    assert check_step("site", "le leboncoin")[1] == "https://www.leboncoin.fr"
    assert check_step("site", "youtube.com")[1] == "https://youtube.com"
    favs.put("ma banque", "https://www.credit-agricole.fr/")
    assert check_step("site", "Ma banque", ctx={"favoris": favs})[1] == "https://www.credit-agricole.fr/"
    assert check_step("site", "site du club de foot")[1] == ("?", "site du club de foot")


def test_site_inconnu_cherche_puis_retenu(tmp_path):
    from motionzero.instruction import Instructeur
    favs = o.Store(str(tmp_path / "f.json"))
    opened = []
    i = Instructeur(lambda a: "", open_url=opened.append, favoris=favs)
    o_find = o.find_site
    try:
        o.find_site = lambda name, f=None: ("https://club.example/", True)
        i._run_tool("site", ("?", "club de foot"))
    finally:
        o.find_site = o_find
    assert opened == ["https://club.example/"] and favs.get("club de foot") == "https://club.example/"


def test_site_recherche_en_panne_ouvre_google():
    def down(q):
        raise OSError("réseau")
    url, searched = o.find_site("truc introuvable", search=down)
    assert url.startswith("https://www.google.com/search?q=") and not searched
    assert o.find_site("truc", search=lambda q: None)[0].startswith("https://www.google.com/search")


def test_aide_sans_modele():
    from motionzero.instruction import Instructeur, is_help
    assert is_help("qu'est-ce que tu sais faire") and is_help("aide") and not is_help("ouvre leboncoin")
    asked = []
    i = Instructeur(lambda a: "aide", ask=lambda p: asked.append(p))
    i._think(b"")
    assert i._q.get_nowait() == ("help",) and asked == []


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


# ---- Discord : salon et message par le bot (affichés avant, rien ne part sans « envoie »)
def test_discord_salon_et_message():
    from types import SimpleNamespace
    from motionzero.instruction import Instructeur
    assert "général" in check_step("discord_message", "dans général, j'arrive dans 5 min")[2]
    with pytest.raises(PlanError):
        check_step("discord_message", "salut")              # sans destinataire
    with pytest.raises(PlanError):
        check_step("discord_salon", "")
    sent = []
    bot = SimpleNamespace(connected=True, send=lambda m: sent.append(m) or 1)
    i = Instructeur(lambda a: "", bot=bot)
    i._run_tool("discord_salon", "Gaming")
    i._run_tool("discord_message", "dans général, salut")
    assert sent == [{"t": "move", "channel": "Gaming"}, {"t": "send", "text": "dans général, salut"}]
    for bad in (None, SimpleNamespace(connected=False, send=lambda m: 1),
                SimpleNamespace(connected=True, send=lambda m: None)):
        with pytest.raises(RuntimeError):
            Instructeur(lambda a: "", bot=bad)._run_tool("discord_salon", "Gaming")


# ---- texte jamais coupé : la police rapetisse
def test_fit_font_texte_entier():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from motionzero.ui import MIN_PT, fit_font
    base = QFont("Atkinson Hyperlegible", 17)
    assert fit_font(base, "court", 500).pointSizeF() == 17
    long = "mot " * 400
    f = fit_font(base, long, 500, 600)
    assert MIN_PT <= f.pointSizeF() < 17
    assert fit_font(base, "x" * 300, 200).pointSizeF() == MIN_PT     # jamais plus petit que lisible


def test_appli_absente_mais_site_connu():
    apps = {"Discord": "x"}
    assert check_step("ouvre_app", "netflix", apps)[:2] == ("site", "https://www.netflix.com")
    with pytest.raises(PlanError):
        check_step("ferme_app", "netflix", apps)              # fermer : jamais remplacé par un site
    with pytest.raises(PlanError):
        check_step("ouvre_app", "zzqq", apps)


def test_bouton_camera_coupe_puis_rallume():
    import queue
    from types import SimpleNamespace
    from motionzero.app import Engine as Loop
    from motionzero.ui import camera_button_text
    from motionzero.voice import WORDS
    assert "caméra" not in WORDS                     # un bouton, jamais un mot de plus pour Vosk
    shown = []
    d = SimpleNamespace(camera_requests=queue.Queue(), cam=SimpleNamespace(paused=False),
                        bridge=SimpleNamespace(camera=SimpleNamespace(emit=shown.append)))
    loop = Loop.__new__(Loop)
    loop.d = d
    d.camera_requests.put(1)
    loop._camera()
    assert d.cam.paused and shown == [True] and "rallumer" in camera_button_text(True)
    d.camera_requests.put(1)
    loop._camera()
    assert not d.cam.paused and shown == [True, False] and "couper" in camera_button_text(False)


def test_camera_en_pause_rend_puis_rouvre_la_webcam(monkeypatch):
    import threading
    import time
    from motionzero import camera as cm

    class Cap:
        released = False
        def read(self):
            time.sleep(0.01)
            return False, None
        def release(self):
            self.released = True
    opened = []
    cam = cm.Camera(lost_after_s=99)
    monkeypatch.setattr(cam, "_open", lambda: opened.append(Cap()) or opened[-1])
    cam.cap, cam.running = Cap(), True
    first = cam.cap
    th = threading.Thread(target=cam._run, daemon=True)
    th.start()
    cam.paused = True
    time.sleep(0.3)
    assert first.released and cam.cap is None and cam.status == cm.PAUSED
    cam.paused = False
    time.sleep(0.3)
    assert opened and cam.cap is opened[0]
    # webcam encore prise ailleurs à la reprise : pas de plantage, nouvelle tentative
    cam.paused = True
    time.sleep(0.3)
    monkeypatch.setattr(cam, "_open", lambda: None)
    cam.paused = False
    time.sleep(0.3)
    assert cam.cap is None and th.is_alive()
    cam.running = False
    th.join(2)


def test_candidature_entendu_meme_dans_une_phrase():
    from motionzero.voice import confirmed
    w = [{"word": "candidature", "conf": 1.0}]
    assert confirmed(w, "l'appli marche plus du tout candidature je dois quitter ce mode", 1)
    assert not confirmed([{"word": "suivante", "conf": 1.0}], "tu as vu la série hier soir avec les copains", 1)


def test_mode_conversation_decoche_plus_de_2e_verification(tmp_path):
    import queue
    from types import SimpleNamespace
    from motionzero.app import Engine, read_conversation
    import motionzero.app as app
    from motionzero.voice import VoiceListener
    assert read_conversation(str(tmp_path / "absent.txt")) is True       # coché par défaut
    (tmp_path / "c.txt").write_text("non", encoding="utf-8")
    assert read_conversation(str(tmp_path / "c.txt")) is False
    # bouton : bascule, enregistre, prévient le micro
    app_conv = tmp_path / "conv.txt"
    old, app.CONV_FILE = app.CONV_FILE, str(app_conv)
    try:
        shown, lis = [], SimpleNamespace(conversation=True)
        d = SimpleNamespace(conversation_requests=queue.Queue(), conversation=True, listener=lis,
                            bridge=SimpleNamespace(conversation=SimpleNamespace(emit=shown.append)))
        e = Engine.__new__(Engine)
        e.d = d
        d.conversation_requests.put(1)
        e._conversation()
        assert lis.conversation is False and shown == [False] and app_conv.read_text(encoding="utf-8") == "non"
        d.listener = None                     # sans la voix : le bouton marche quand même
        d.conversation_requests.put(1)
        e._conversation()
        assert d.conversation is True and app_conv.read_text(encoding="utf-8") == "oui"
    finally:
        app.CONV_FILE = old
    # micro : mot noyé dans une phrase -> ignoré si coché, accepté si décoché
    got = []
    v = VoiceListener.__new__(VoiceListener)
    v.min_conf, v._iris_ok_t, v.quiet, v.last_rejected = 0.6, -1e9, False, None
    v._handle = lambda *a, **k: got.append(a)
    res = {"result": [{"word": "suivante", "conf": 1.0, "start": 0.0, "end": 0.4}], "text": "suivante"}
    long = "tu as vu la série hier soir avec les copains suivante"
    v.conversation = True
    v._emit(res, long)
    assert v.last_rejected is not None
    v.last_rejected = None
    v.conversation = False
    try:
        v._emit(res, long)
    except AttributeError:
        pass                                  # la suite de _emit (file de mots) n'est pas montée ici
    assert v.last_rejected is None            # décoché : jamais « pas sûr de l'avoir entendu »


def test_ferme_ne_ferme_jamais_le_dernier_onglet():
    from motionzero.app import last_tab
    assert last_tab(1) and last_tab(0)            # dernier onglet, ou choix du profil : on ne touche à rien
    assert not last_tab(2) and not last_tab(None)  # plusieurs onglets, ou illisible : Ctrl+W comme avant
