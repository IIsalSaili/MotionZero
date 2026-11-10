"""Commandes vocales, sans micro : filtrage des résultats Vosk et logique mot + geste."""
from synth import Clock

from motionzero.config import Config
from motionzero.core import Core, Mode
from motionzero.output import Controller, FakeBackend
from motionzero.voice import accepted_words


def res(*words):
    return {"result": [{"word": w, "conf": c, "start": 0.0, "end": 0.3} for w, c in words]}


# --- filtrage -----------------------------------------------------------------
def test_mot_dit_seul_accepte():
    assert [w["word"] for w in accepted_words(res(("clic", 1.0)))] == ["clic"]


def test_phrase_avec_mots_inconnus_ignoree():
    assert accepted_words(res(("[unk]", 0.5), ("iris", 0.87), ("[unk]", 0.6))) == []


def test_plusieurs_commandes_d_affilee_ignorees():
    """« arrête de faire défiler » donnait annule + défile + défile : refusé."""
    assert accepted_words(res(("annule", 0.72), ("défile", 0.97), ("défile", 1.0))) == []


def test_confiance_faible_ignoree():
    assert accepted_words(res(("clic", 0.4))) == []


# --- écoute ---------------------------------------------------------------------
def test_commande_ignoree_sans_iris():
    core = Core(Config())
    assert core.voice("clic", 1.0) == []
    assert core.last_word == ("clic", 1.0, False)


def test_iris_puis_clic():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.listening(2.0)
    assert core.voice("clic", 2.0) == [("click", "left")]


def test_ecoute_courte_et_une_seule_commande():
    """Mesuré : 8 s prolongées laissaient passer « colle », « chrome » dits dans la conversation."""
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("clic", 3.0) == [("click", "left")]   # « iris » seul puis le mot : marche
    assert core.voice("clic", 3.5) == []                     # 2e mot sans « iris » : ignoré
    core.voice("iris", 10.0)
    assert core.voice("clic", 14.0) == []                    # plus de 3,5 s après « iris » : fermée


def test_mot_seul_peu_sur_refuse():
    from motionzero.voice import accepted_words
    one = lambda w, c: {"result": [{"word": w, "conf": c, "start": 0.0, "end": 0.3}]}
    assert accepted_words(one("tab", 0.60)) == [] and accepted_words(one("colle", 0.79)) == []
    assert accepted_words(one("clic", 0.95))[0]["word"] == "clic"


def test_page_n_est_plus_un_mot_vocal():
    """La voix ne double pas les gestes : les pages se tournent avec la paume au bord."""
    from motionzero.voice import WORDS
    assert "page" not in WORDS


def test_iris_tab_passe_a_la_fenetre_suivante():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("tab", 1.5) == [("alt_tab",)]


def test_tab_exige_iris():
    core = Core(Config())
    assert core.voice("tab", 1.2) == []


def test_main_immobile_ouvre_l_ecoute_sans_iris():
    """Le menu (main immobile) ouvre l'écoute : on peut dire « menu » au lieu de bouger."""
    core, clk = Core(Config(mouse_bubble=True, start_mode="LECTURE")), Clock()     # ancienne bulle, en option
    clk.run(core, 1.7, cx=0.5, cy=0.6)
    assert core.bubble is not None and core.listening(clk.t)
    assert core.voice("menu", clk.t) == [("click", "right")]


def test_stop_toujours_ecoute_et_prioritaire():
    core = Core(Config())
    core.mode = Mode.MOUSE
    acts = core.voice("stop", 1.0)
    assert ("release_all",) in acts and core.mode == Mode.NEUTRAL


def test_pause_puis_iris_reprend():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("pause", 1.5)
    assert core.mode == Mode.DISABLED
    assert core.voice("clic", 2.0) == []
    core.voice("iris", 3.0)
    assert core.mode == Mode.NEUTRAL


def test_raccourcis_clavier_vocaux():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("copie", 1.5) == [("hotkey", ["ctrl", "c"])]
    fake = FakeBackend()
    Controller(fake, Config()).execute([("hotkey", ["ctrl", "c"])], 0.0)
    assert fake.events == [("key", "ctrl", True), ("key", "c", True), ("key", "c", False), ("key", "ctrl", False)]


def test_glisse_lache_et_securite():
    core = Core(Config())
    core.voice("iris", 1.0)
    fake = FakeBackend()
    ctl = Controller(fake, Config())
    ctl.execute(core.voice("glisse", 1.2), 1.2)
    assert ("button", "left", True) in fake.events
    ctl.execute(core.voice("lâche", 9.0), 9.0)               # longtemps après, sans « iris » : relâché quand même
    assert fake.events[-1] == ("button", "left", False)


# --- mot + geste : « défile » ------------------------------------------------------
def test_defile_main_qui_descend_defile_vers_le_bas():
    core, clk = Core(Config()), Clock()
    clk.run(core, 0.3, cx=0.5, cy=0.6)
    core.voice("iris", clk.t)
    core.voice("défile", clk.t)
    acts = clk.run(core, 0.3, cx=0.5, cy=0.6, to_cy=0.75) + clk.run(core, 1.0, cx=0.5, cy=0.75)
    scrolls = [a for a in acts if a[0] == "scroll"]
    assert len(scrolls) >= 3 and all(s[1] < 0 for s in scrolls)
    assert not [a for a in acts if a[0] == "key"]  # pas de page pendant le défilement vocal


def test_defile_main_immobile_ne_defile_pas():
    core, clk = Core(Config()), Clock()
    clk.run(core, 0.3, cx=0.5, cy=0.6)
    core.voice("iris", clk.t)
    core.voice("défile", clk.t)
    acts = clk.run(core, 1.0, cx=0.5, cy=0.6)
    assert not [a for a in acts if a[0] == "scroll"]


def test_iris_et_commande_d_une_traite():
    from motionzero.voice import accepted_words, rejection
    w = lambda *ws: {"result": [{"word": x, "conf": c, "start": 0, "end": 1} for x, c in ws]}
    assert [x["word"] for x in accepted_words(w(("iris", 1.0), ("claude", 1.0)))] == ["iris", "claude"]
    # ordre inverse : seul « iris » compte (il ouvre l'écoute), « claude » d'avant est ignoré
    assert [x["word"] for x in accepted_words(w(("claude", 1.0), ("iris", 1.0)))] == ["iris"]
    # ce qui suit la commande (la dictée qui commence, du bruit) ne l'annule plus
    assert [x["word"] for x in accepted_words(w(("iris", 1.0), ("claude", 1.0), ("clic", 1.0)))] == ["iris", "claude"]
    assert accepted_words(w(("iris", 0.4), ("claude", 1.0))) == []
    assert rejection(w(("iris", 0.4), ("claude", 1.0))) == "iris(0.40) claude(1.00)"


def test_iris_claude_d_une_traite_lance_la_dictee():
    from motionzero.config import Config
    from motionzero.core import Core
    core = Core(Config())
    assert core.voice("iris", 1.0) == []
    assert core.voice("claude", 1.0) == [("vscode_dictation",)]


def test_bruit_autour_de_iris_tolere():
    from motionzero.voice import accepted_words
    w = lambda *ws: {"result": [{"word": x, "conf": 1.0, "start": 0, "end": 1} for x in ws]}
    assert [x["word"] for x in accepted_words(w("[unk]", "iris", "claude"))] == ["iris", "claude"]
    # bruit de fond avant : toléré (la 2e vérification exige « iris » vraiment prononcé)
    assert [x["word"] for x in accepted_words(w("[unk]", "iris"))] == ["iris"]
    assert [x["word"] for x in accepted_words(w("[unk]", "[unk]", "iris", "claude"))] == ["iris", "claude"]
    assert accepted_words(w("[unk]", "clic")) == []          # sans « iris » : toujours dit seul


def test_iris_discord_et_chrome_ouvrent_l_appli():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("discord", 1.5) == [("open_app", "discord")]
    core.voice("iris", 2.0)
    assert core.voice("chrome", 2.5) == [("open_app", "chrome")]


def test_iris_mute_et_demute():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("mute", 1.5) == [("discord_mute",)]
    core.voice("iris", 2.0)
    assert core.voice("démute", 2.5) == [("discord_unmute",)]


def test_des_mute_est_compris_comme_demute():
    """« démute » n'existe pas dans le modèle vocal : on entend « des » + « mute »."""
    r = {"result": [{"word": "iris", "conf": 1.0, "start": 0.0, "end": 0.3},
                    {"word": "des", "conf": 0.9, "start": 0.4, "end": 0.5},
                    {"word": "mute", "conf": 0.95, "start": 0.5, "end": 0.8}]}
    assert [w["word"] for w in accepted_words(r)] == ["iris", "démute"]


def test_deuxieme_verification():
    """Mesuré avec la voix de synthèse : la reconnaissance libre retrouve « iris » dans les vraies commandes,
    et la conversation donne des phrases longues."""
    from motionzero.voice import confirmed
    w = lambda *names: [{"word": n} for n in names]
    assert confirmed(w("iris", "chrome"), "iris chrome")
    assert confirmed(w("iris", "discord"), "iris discorde")
    assert not confirmed(w("iris", "chrome"), "je vais regarder ça sur chrome")
    assert not confirmed(w("envoie"), "tu as vu la série hier soir")
    assert not confirmed(w("iris", "colle"), "il colle")            # pas de « iris » prononcé
    assert confirmed(w("stop"), "arrête stop tout de suite là")    # sécurité : jamais bloqué
    assert confirmed(w("lâche"), "")


def test_phrase_vide_ne_fait_pas_planter_l_ecoute():
    """Mesuré : un résultat vide faisait planter le fil d'écoute, plus aucune commande n'était entendue."""
    from motionzero.voice import VoiceListener
    v = VoiceListener.__new__(VoiceListener)
    import queue
    v.events, v.min_conf = queue.Queue(), 0.6
    v._emit({"result": [], "text": ""}, "")
    v._emit({"text": ""}, "")
    assert v.events.empty()


def test_iris_claude_colle_au_bruit_de_fond():
    """Mesuré le 10/11 avec une vidéo en fond : « stop pause stop iris claude » était rejeté."""
    r = lambda *ws: {"result": [{"word": w, "conf": c, "start": 0.0, "end": 0.1} for w, c in ws]}
    got = accepted_words(r(("stop", 0.64), ("pause", 0.65), ("stop", 0.99), ("iris", 1.0), ("claude", 1.0)))
    assert [w["word"] for w in got] == ["iris", "claude"]
    got = accepted_words(r(("stop", 0.63), ("[unk]", 1.0), ("iris", 1.0), ("claude", 1.0), ("[unk]", 1.0)))
    assert [w["word"] for w in got] == ["iris", "claude"]
    from motionzero.voice import confirmed
    assert confirmed(got, "le grès n'attend pas iris claude et je voudrais")    # « iris » bien entendu
    assert not confirmed(got, "le grès n'attend pas le temps alors et des puzzles")


def test_iris_claude_dit_vite_passe_sans_deuxieme_avis():
    """Mesuré le 10/11 : dit vite, la reconnaissance libre entendait « la france » et bloquait la commande."""
    from motionzero.voice import confirmed
    fast = [{"word": "iris", "conf": 1.0}, {"word": "claude", "conf": 1.0}]
    assert confirmed(fast, "la france", n_heard=2)
    assert confirmed(fast, "les récents voyez", n_heard=3)
    assert not confirmed(fast, "la france", n_heard=6)                    # collé à d'autres paroles : 2e avis
    unsure = [{"word": "iris", "conf": 0.7}, {"word": "claude", "conf": 1.0}]
    assert not confirmed(unsure, "la france", n_heard=2)                   # « iris » pas net : 2e avis
    assert not confirmed([{"word": "discord", "conf": 1.0}], "d'accord mais du coup je", n_heard=1)


def test_iris_studio_passe_sur_vs_code_sans_micro():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("studio", 1.5) == [("open_app", "studio")]
    assert not core.dictating


def test_iris_question_enregistre_puis_envoie_apres_le_silence():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("question", 1.2) == [("ask_start",)] and core.asking
    assert core.voice("iris", 2.0) == [] and core.voice("chrome", 2.1) == []   # la question n'est pas une commande
    assert core.ask_tick(3.0, last_speech_t=2.5) == []                         # on parle encore
    assert core.ask_tick(5.4, last_speech_t=2.5) == [("ask_stop",)] and not core.asking
    core.voice("iris", 6.0)
    assert core.voice("ferme", 6.2) == [("ask_close",)]


def test_iris_question_sans_rien_dire_est_annulee():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("question", 1.2)
    assert core.ask_tick(9.5, last_speech_t=0.0) == [("ask_cancel",)] and not core.asking


def test_iris_defun_sourdine_discord():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("défun", 1.5) == [("discord_deafen",)]


def test_des_fun_et_dis_fun_sont_compris_comme_defun():
    for first in ("des", "dis"):
        r = {"result": [{"word": "iris", "conf": 1.0, "start": 0.0, "end": 0.3},
                        {"word": first, "conf": 0.9, "start": 0.4, "end": 0.5},
                        {"word": "fun", "conf": 0.95, "start": 0.5, "end": 0.8}]}
        assert [w["word"] for w in accepted_words(r)] == ["iris", "défun"]
