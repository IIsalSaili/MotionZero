"""Page d'accueil (#35) : contenu calculé, dessin Qt, et arrêt propre au STOP."""
from types import SimpleNamespace

from motionzero.accueil import conso_line, home_view, last_commands, now_view, sensors, state_text
from motionzero.aide import now_block
from motionzero.core import Mode


def test_etat_de_la_bande():
    assert state_text(Mode.NEUTRAL) == ("Prêt", "idle")
    assert state_text(Mode.NEUTRAL, listening=True)[0] == "J'écoute"
    assert state_text(Mode.CHROME, listening=True, dictating=True)[0] == "Dictée en cours"
    assert state_text(Mode.NEUTRAL, confirming=True)[0] == "Envoie ou annule ?"
    assert state_text(Mode.DISABLED, listening=True)[0] == "En pause"       # la pause passe avant tout
    assert state_text(Mode.NEUTRAL, voice_on=False)[0] == "Voix coupée"
    assert state_text(Mode.NEUTRAL, listening=True, mic_muted=True)[0] == "Micro coupé"


def test_ici_maintenant_vient_de_l_aide():
    # même source que « iris aide » : rien d'écrit à la main
    assert now_view(Mode.CHROME) == now_block(Mode.CHROME)
    assert now_view(Mode.NEUTRAL, calendar_open=True) == now_block(Mode.NEUTRAL, True)
    title, rows = now_view(Mode.NEUTRAL, mouse=True)
    assert title == "Souris allumée" and any("clic" in w for w, _ in rows)
    # Chrome reste prioritaire sur la souris, la dictée aussi
    assert now_view(Mode.CHROME, mouse=True) == now_block(Mode.CHROME)
    assert now_view(Mode.NEUTRAL, mouse=True, confirming=True) == now_block(Mode.NEUTRAL, confirming=True)


def test_plus_d_aide_perimee_dans_l_image():
    import motionzero.overlay as ov
    assert not hasattr(ov, "HELP") and not hasattr(ov, "VOICE_HELP")


def test_capteurs():
    names = [n for n, _, _ in sensors()]
    assert names == ["Caméra", "Micro", "Whisper", "Bot Discord", "Gardien"]
    st = {n: s for n, s, _ in sensors(cam_status="perdue", voice_on=True, mic_stalled=True, whisper=False,
                                      bot_enabled=True, bot_connected=False, guard=False)}
    assert st == {"Caméra": "fail", "Micro": "fail", "Whisper": "idle", "Bot Discord": "fail", "Gardien": "fail"}
    st = {n: s for n, s, _ in sensors(voice_on=False, bot_enabled=False, whisper=True, bot_connected=True)}
    assert st["Micro"] == "off" and st["Bot Discord"] == "off" and st["Whisper"] == "ok"
    assert {n: s for n, s, _ in sensors(mic_muted=True)}["Micro"] == "off"


def test_dernieres_commandes():
    feed = [("PAGE PRECEDENTE", 1.0), ("MODE CHROME", 8.0), ("souris ignoree", 9.0), ("TRES VIEUX", -100.0)]
    out = last_commands(feed, rejected=("« bas » ignoré : pas sûr", 9.5), now=10.0)
    assert [lab for lab, _, _ in out] == ["« bas » ignoré : pas sûr", "souris ignoree", "Mode chrome"]
    assert [ok for _, ok, _ in out] == [False, False, True]
    assert last_commands([], None, now=5.0) == []
    assert last_commands(None, None) == []


def test_ligne_de_consommation():
    assert "mesure en cours" in conso_line(None)
    assert conso_line({"ncpu": 12}) == "Iris 0 % CPU · 0 Mo"          # mesure presque vide : pas de plantage
    line = conso_line({"app_cpu": 12.3, "app_private": 840, "app_gpu": 30, "pc_cpu": 34})
    assert line == "Iris 12 % CPU · 840 Mo · GPU 30 % · PC 34 %"


def test_page_se_dessine_dans_tous_les_cas():
    from motionzero.ui import PreviewWindow, QApplication
    import numpy as np
    QApplication.instance() or QApplication([])
    w = PreviewWindow(pointer="tete", quiet="oui", volume=0.3)
    w.grab()
    for mode in (Mode.NEUTRAL, Mode.CHROME, Mode.READING, Mode.DISABLED, "INCONNU"):
        v = home_view(mode, mouse=True, listening=True, sensor_list=sensors(cam_status="perdue"),
                      feed=[("<b>balise</b> & co", 1.0)], now=2.0)
        w.set_home(v)
        w.grab()
    w.set_home({})                              # contenu vide : pas de plantage
    w.set_stats(None)
    w.set_stats({"app_cpu": 5})
    w.set_frame(np.zeros((480, 640, 3), np.uint8))
    w.grab()


def test_main_tete_au_clic():
    from motionzero.ui import PreviewWindow, QApplication
    QApplication.instance() or QApplication([])
    w = PreviewWindow(pointer="main")
    clicks = []
    w.pointer_clicked.connect(lambda: clicks.append(w.pointer))
    w.main_btn.click()                          # déjà à la main : rien
    w.head_btn.click()
    w.head_btn.click()                          # déjà à la tête : rien
    assert clicks == ["tete"]


def test_moteur_publie_l_accueil(monkeypatch):
    from motionzero import app
    monkeypatch.setattr("motionzero.garde.guard_running", lambda: True)
    sent = []
    lis = SimpleNamespace(muted=False, t_stream0=0.0, last_block_t=9.9, last_rejected=None)
    core = SimpleNamespace(mode=Mode.CHROME, mouse=False, pointer="main", listening=lambda t: True,
                           dictating=False, confirming=lambda t: False, calendar_until=0.0,
                           feed=[("ONGLET SUIVANT", 9.0)])
    d = SimpleNamespace(core=core, listener=lis, asker=SimpleNamespace(_whisper=None),
                        bot=SimpleNamespace(enabled=True, connected=True),
                        bridge=SimpleNamespace(home=SimpleNamespace(emit=sent.append)))
    eng = app.Engine.__new__(app.Engine)
    eng.d, eng.guard_t, eng.guard_on = d, -1e9, False
    v = eng.home("ok", 10.0)
    assert v["state"] == "J'écoute" and v["mode"] == "CHROME"
    assert {n: s for n, s, _ in v["sensors"]} == {"Caméra": "ok", "Micro": "ok", "Whisper": "idle",
                                                  "Bot Discord": "ok", "Gardien": "ok"}
    assert v["last"][0][0] == "Onglet suivant"
    # micro figé (aucun son depuis 5 s) et voix coupée
    lis.last_block_t = 5.0
    assert {n: s for n, s, _ in eng.home("ok", 10.0)["sensors"]}["Micro"] == "fail"
    d.listener = None
    assert eng.home("ok", 10.0)["state"] == "Voix coupée"


def test_gardien_illisible_ne_plante_pas(monkeypatch):
    from motionzero import app

    def boom():
        raise OSError("kernel32")
    monkeypatch.setattr("motionzero.garde.guard_running", boom)
    core = SimpleNamespace(mode=Mode.NEUTRAL, mouse=False, pointer="main", listening=lambda t: False,
                           dictating=False, confirming=lambda t: False, calendar_until=0.0, feed=[])
    d = SimpleNamespace(core=core, listener=None, asker=SimpleNamespace(_whisper=None),
                        bot=SimpleNamespace(enabled=False, connected=False))
    eng = app.Engine.__new__(app.Engine)
    eng.d, eng.guard_t, eng.guard_on = d, -1e9, True
    assert {n: s for n, s, _ in eng.home("ok", 1.0)["sensors"]}["Gardien"] == "fail"


def test_sortie_forcee_relache_tout_meme_en_panne():
    from motionzero.app import force_exit
    codes, released = [], []
    force_exit(SimpleNamespace(release_all=lambda: released.append(1)), exit=codes.append)
    assert released == [1] and codes == [0]

    def boom():
        raise RuntimeError("SendInput")
    force_exit(SimpleNamespace(release_all=boom), exit=codes.append)   # relâchement en panne : on sort quand même
    assert codes == [0, 0]


def test_iris_accueil_retrouve_la_fenetre():
    # « iris accueil » cherche la fenêtre par son titre : les deux doivent rester liés (régression du 14/11)
    from motionzero.ui import PreviewWindow, QApplication
    import inspect
    from motionzero import vscode
    from motionzero.accueil import HOME_TITLE
    QApplication.instance() or QApplication([])
    assert PreviewWindow().windowTitle() == HOME_TITLE
    assert "== HOME_TITLE" in inspect.getsource(vscode)
