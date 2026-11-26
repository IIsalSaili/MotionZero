"""« iris instruction » (#45) : plan vérifié, affiché, exécuté après « envoie » ; échecs."""
import json
import re
import time
from types import SimpleNamespace

import pytest

from motionzero import instruction as ins
from motionzero.instruction import Instructeur, PlanError, check_plan, check_step
from motionzero.ui import reminder_texts, reminder_view


class FakeCore:
    def __init__(self):
        self.confirm_until, self.confirm_kind, self.last_gesture = -1e9, None, None
        self.cmds = []

    def ask_confirm(self, kind, t, s):
        self.confirm_kind, self.confirm_until = kind, t + s

    def confirming(self, t):
        return t < self.confirm_until

    def _cmd_translator(self, word, t, acts):
        self.cmds.append(word)
        acts.append(("traducteur", True))


def _pump(instr, core, t, until, timeout=2.0):
    end = time.time() + timeout
    acts = []
    while time.time() < end:
        acts += instr.events(core, t)
        if until():
            return acts
        time.sleep(0.01)
    raise AssertionError("delai depasse")


def _instr(raw, ran=None, transcribe=lambda a: "ouvre la derniere video de one click studio", **kw):
    ran = ran if ran is not None else []
    return Instructeur(transcribe, ask=lambda phrase: raw,
                       runner=lambda outil, arg: ran.append((outil, arg)), **kw), ran


PLAN = {"etapes": [{"outil": "youtube", "arg": "One Click Studio"},
                   {"outil": "touche", "arg": "f"}], "refus": ""}


# ---- vérification du plan
def test_plan_valide_et_libelles():
    plan = check_plan(PLAN)
    assert [o for o, _, _ in plan] == ["youtube", "touche"]
    assert plan[1][1] == ["f"] and "One Click Studio" in plan[0][2]


@pytest.mark.parametrize("outil,arg", [("shell", "rm -rf"), ("site", ""),
                                       ("volume", "beaucoup"), ("discord", "danse"), ("timer", "10 minutes"), ("chronometre", ""),
                                       ("ecris", ""), ("attends", "longtemps"), ("ouvre_app", "")])
def test_etape_refusee(outil, arg):
    with pytest.raises(PlanError):
        check_step(outil, arg)


def test_refus_du_modele_et_plan_trop_long():
    with pytest.raises(PlanError, match="impossible"):
        check_plan({"etapes": [], "refus": "impossible avec mes outils"})
    with pytest.raises(PlanError):
        check_plan({"etapes": [{"outil": "touche", "arg": "f"}] * (ins.MAX_STEPS + 1), "refus": ""})
    with pytest.raises(PlanError):
        check_plan("pas un dict")


@pytest.mark.parametrize("outil,arg", [("ouvre_app", "explorer"), ("ouvre_app", "PowerShell"),
                                       ("ouvre_app", "invite de commandes"), ("ecris", "del *.*"),
                                       ("ecris", "C:\\Users\\moi\\Documents\\"), ("ecris", "rm -rf /"),
                                       # jamais : fichiers, arrêt de l'ordinateur, réglages (17/11)
                                       ("touche", "win+x"), ("touche", "win"), ("touche", "alt+f4"),
                                       ("touche", "ctrl+s"), ("touche", "delete"), ("touche", "shift+delete"),
                                       ("touche", "ctrl+shift+escape"), ("touche", "ctrl+alt+delete"),
                                       ("touche", "win+r"), ("touche", "ctrl+a"), ("touche", "ctrl+x"),
                                       ("ouvre_app", "Paramètres"), ("ouvre_app", "Panneau de configuration"),
                                       ("ouvre_app", "Gestionnaire des tâches"), ("ouvre_app", "Options d'alimentation"),
                                       ("ouvre_app", "Windows Update"), ("ouvre_app", "Corbeille"),
                                       ("ouvre_app", "Explorateur de fichiers"), ("ouvre_app", "Exécuter"),
                                       ("ferme_app", "Iris")])
def test_garde_fous_console_et_commandes(outil, arg):
    with pytest.raises(PlanError, match="interdit"):
        check_step(outil, arg)


def test_plan_dangereux_du_modele_refuse_en_entier():
    raw = {"etapes": [{"outil": "ouvre_app", "arg": "explorer"}, {"outil": "ecris", "arg": "del"},
                      {"outil": "touche", "arg": "entrée"}], "refus": ""}
    with pytest.raises(PlanError):
        check_plan(raw)
    assert check_step("ecris", "bonjour, je rentre vers 18 h")[1].startswith("bonjour")
    for k in ("f", "k", "entrée", "ctrl+t", "alt+tab", "espace", "f5"):   # lecture, navigation : permis
        assert check_step("touche", k)
    for app in ("Discord", "Google Chrome", "PowerPoint", "Spotify"):
        assert check_step("ouvre_app", app)


def test_aucun_outil_de_fichier_d_arret_ou_de_reglage():
    banned = re.compile(r"fichier|supprim|dossier|eteind|arret|redemarr|reglage|parametre|shell|commande", re.I)
    assert not [t for t in ins.TOOLS if banned.search(t)]


def test_appli_inconnue_refusee_et_connue_resolue():
    apps = {"Google Chrome": "id1", "Discord": "id2"}
    assert check_step("ouvre_app", "chrome", apps)[1] == "Google Chrome"
    with pytest.raises(PlanError):
        check_step("ouvre_app", "zzzqqq", apps)


def test_touches_et_adresse():
    assert check_step("touche", "ctrl + t")[1] == ["ctrl", "t"]
    assert check_step("touche", "entrée")[1] == ["enter"]
    assert check_step("site", "youtube.com")[1] == "https://youtube.com"
    assert check_step("attends", "60")[1] == 10.0


# ---- YouTube sans clic
def test_youtube_rien_trouve():
    with pytest.raises(RuntimeError):
        ins.youtube_first("x", lambda url: "rien")


# ---- flux complet : affiché, rien fait avant « envoie »
def test_plan_affiche_puis_execute_apres_envoie():
    instr, ran = _instr(PLAN)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    assert ran == []                                         # rien fait avant la confirmation
    assert core.confirm_kind == "instruction" and core.confirming(1.0)
    st = instr.state(1.0)
    assert st["lines"][0].startswith("1. YouTube") and "oui" in st["title"]
    assert reminder_view({"plan": st})[0] == "plan"
    assert "oui" in reminder_texts("plan", st)[2]
    rest = instr.actions([("instruction_ok",), ("autre",)], core, 1.0)
    assert rest == [("autre",)]
    _pump(instr, core, 2.0, lambda: not instr.busy)
    assert [o for o, _ in ran] == ["youtube", "touche"]
    assert instr.title == "Instruction faite" and all("fait" in l for l in instr.state(2.0)["lines"])


def test_annule_rien_n_est_fait():
    instr, ran = _instr(PLAN)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    instr.actions([("instruction_non",)], core, 1.0)
    instr.actions([("instruction_ok",)], core, 1.1)          # « envoie » trop tard : plus rien en attente
    time.sleep(0.05)
    assert ran == [] and instr.state(1.2) is None


def test_plan_expire_sans_reponse():
    instr, ran = _instr(PLAN)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    instr.events(core, ins.CONFIRM_S + 1)
    assert instr.plan is None and instr.state(ins.CONFIRM_S + 1) is None


def test_rien_entendu():
    instr, _ = _instr(PLAN, transcribe=lambda a: "  ")
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.lines is not None)
    assert "rien entendu" in instr.lines and core.confirm_kind is None


def test_modele_indisponible():
    def down(phrase):
        raise RuntimeError("modèle local indisponible (Ollama)")
    instr = Instructeur(lambda a: "fais un truc", ask=down, runner=lambda o, a: None)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.lines is not None)
    assert "Ollama" in instr.lines[-2] and "aide" in instr.lines[-1] and instr.title == "Instruction impossible"


def test_reponse_illisible_et_whisper_en_panne():
    def boom(a):
        raise RuntimeError("CUDA")
    for instr in (Instructeur(lambda a: "x", ask=lambda p: (_ for _ in ()).throw(ValueError("json"))),
                  Instructeur(boom, ask=lambda p: PLAN)):
        core = FakeCore()
        instr.submit(b"")
        _pump(instr, core, 0.0, lambda: instr.lines is not None)
        assert instr.plan is None


def test_etape_en_echec_arrete_la_suite():
    calls = []

    def runner(outil, arg):
        calls.append(outil)
        raise RuntimeError("aucune vidéo trouvée")
    instr = Instructeur(lambda a: "x", ask=lambda p: PLAN, runner=runner)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    instr.actions([("instruction_ok",)], core, 1.0)
    _pump(instr, core, 2.0, lambda: not instr.busy)
    assert calls == ["youtube"] and "échec" in instr.lines[0]


def test_stop_arrete_entre_deux_etapes(monkeypatch):
    monkeypatch.setattr("motionzero.instruction_outils.STEP_PAUSE_S", 0.3)
    instr, ran = _instr(PLAN)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    instr.actions([("instruction_ok",)], core, 1.0)
    _pump(instr, core, 1.0, lambda: len(ran) == 1)
    assert instr.actions([("release_all",)], core, 1.1) == [("release_all",)]   # « stop » garde son effet
    _pump(instr, core, 2.0, lambda: not instr.busy)
    assert len(ran) == 1 and instr.title == "Instruction interrompue"


def test_discord_et_traducteur_par_la_boucle_principale():
    raw = {"etapes": [{"outil": "discord", "arg": "coupe"}, {"outil": "traducteur", "arg": ""}], "refus": ""}
    instr = Instructeur(lambda a: "x", ask=lambda p: raw)
    instr.open_url = None
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    instr.actions([("instruction_ok",)], core, 1.0)
    acts = _pump(instr, core, 2.0, lambda: not instr.busy)
    acts += instr.events(core, 2.1)
    assert ("discord_mute",) in acts and core.cmds == ["traducteur"]


# ---- Core : écoute de la phrase et confirmation
def test_core_instruction_ecoute_puis_confirmation():
    from motionzero.core import COMMANDS, OPEN_STOP
    from motionzero.voice import GRAMMAR, WORDS
    assert COMMANDS["instruction"] == "listen" and OPEN_STOP["instruction"] == "instruction_stop"
    assert WORDS["instruction"] == "instruction" and '"instruction"' in GRAMMAR


def test_core_envoie_annule():
    from motionzero.core import Core
    core = Core.__new__(Core)
    core.confirm_until, core.confirm_kind, core.type_erase_until = 10.0, "instruction", -1e9
    assert core._v_confirm("envoie", 1.0, 1.0, []) is None      # 26/11 : plus « envoie », seulement « oui »
    assert core._v_confirm("oui", 1.0, 1.0, []) == [("instruction_ok",)]
    core.confirm_until = 10.0
    assert core._v_confirm("annule", 2.0, 2.0, []) == [("instruction_non",)]
    assert not core.confirming(3.0)


# ---- fermer la carte (17/11 : la carte d'aide ne se fermait pas)
@pytest.mark.parametrize("act", ["rappel_merci", "ask_close"])
def test_merci_et_ferme_ferment_la_carte(act):
    instr = Instructeur(lambda a: "aide")
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.lines is not None)
    assert "iris merci" in instr.state(1.0)["meta"]
    assert instr.actions([(act,)], core, 1.0) == [(act,)]     # rappels et réponses se ferment aussi
    assert instr.state(1.1) is None


def test_merci_abandonne_un_plan_en_attente():
    instr, ran = _instr(PLAN)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    instr.actions([("rappel_merci",)], core, 1.0)
    instr.actions([("instruction_ok",)], core, 1.1)
    time.sleep(0.05)
    assert ran == [] and not core.confirming(1.2) and instr.state(1.2) is None


def test_aide_lisible():
    from motionzero.outils import EXAMPLES
    assert len(EXAMPLES) <= 8 and all(e.startswith("«") and "·" not in e for e in EXAMPLES)


# ---- commandes passées dans « instruction » (17/11)
def test_timer_et_chronometre_hors_instruction():
    """26/11 : redevenus des mots à part (« iris timer », « iris chronomètre »), plus des outils."""
    from motionzero.voice import GRAMMARS
    assert "timer" not in ins.TOOLS and "chronometre" not in ins.TOOLS
    assert all("timer" in json.loads(g) and "chronomètre" in json.loads(g)
               for k, g in GRAMMARS.items() if not k.startswith("candidature"))


def test_commandes_directes_sans_envoie():
    raw = {"etapes": [{"outil": "site", "arg": "youtube.com"}, {"outil": "volume", "arg": "40"},
                      {"outil": "rappel", "arg": "demain 9 h médecin"}], "refus": ""}
    instr, ran = _instr(raw)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: not instr.busy and len(ran) == 3)
    assert [o for o, _ in ran] == ["site", "volume", "rappel"] and core.confirm_kind is None


def test_plan_melange_demande_toujours_envoie():
    raw = {"etapes": [{"outil": "volume", "arg": "40"}, {"outil": "touche", "arg": "f"}], "refus": ""}
    instr, ran = _instr(raw)
    core = FakeCore()
    instr.submit(b"")
    _pump(instr, core, 0.0, lambda: instr.plan is not None)
    time.sleep(0.1)
    instr.events(core, 0.5)
    assert ran == [] and core.confirm_kind == "instruction"


def test_rappel_direct_enregistre_sans_confirmation(tmp_path):
    import datetime as dt
    from motionzero.reminders import Desk, Reminders
    now = dt.datetime(2026, 11, 17, 15, 0)
    reply = '{"action": "create", "text": "appeler le médecin", "at": "2026-11-18T09:00", "repeat": null}'
    desk = Desk(Reminders(str(tmp_path / "r.json")).load(now), None, None, None, ask=lambda q: reply,
                transcribe=lambda a: a, clock=lambda: now)
    core = FakeCore()
    desk.submit("demain 9 h appeler le médecin", confirm=False)
    end = time.time() + 2
    while time.time() < end and not desk.r.items:
        desk.events(core, 1.0)
        time.sleep(0.01)
    assert [r.text for r in desk.r.items] == ["appeler le médecin"] and core.confirm_kind is None
    assert "ENREGISTRE" in core.last_gesture[0]


def test_mots_passes_plus_guettes_mais_compris_en_mp():
    from motionzero.discord_cmd import VOCAB, parse
    from motionzero.voice import GRAMMARS, VIA_INSTRUCTION
    for w in VIA_INSTRUCTION:
        assert all(w not in json.loads(g) for g in GRAMMARS.values())
    assert "chronomètre" in VOCAB and parse("chronomètre")[0] == "chronomètre"
    assert parse("timer 10 minutes")[:2] == ("timer", "10 minutes")


def _ollama_absent(monkeypatch):
    from motionzero import instruction_base as instruction   # #52 : ensure_ollama vit là
    def no_http(*a, **k):
        raise OSError("pas de serveur")
    monkeypatch.setattr(instruction, "_http", no_http)
    monkeypatch.setattr(instruction.time, "sleep", lambda s: None)
    return instruction


def test_ollama_lance_avec_console_cachee_jamais_detache(monkeypatch):
    """Sans console (DETACHED_PROCESS), ses enfants ouvraient chacun une fenêtre visible (18/11)."""
    import subprocess
    instruction = _ollama_absent(monkeypatch)
    seen = {}
    monkeypatch.setattr(instruction.subprocess, "Popen", lambda cmd, **k: seen.update(k))
    assert instruction.ensure_ollama(wait_s=0.0) is False      # jamais répondu : échec, pas d'exception
    flags = seen["creationflags"]
    assert flags & getattr(subprocess, "CREATE_NO_WINDOW", 0) == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert not flags & getattr(subprocess, "DETACHED_PROCESS", 0x8)


def test_ollama_introuvable_renvoie_false(monkeypatch):
    instruction = _ollama_absent(monkeypatch)
    def absent(*a, **k):
        raise OSError("introuvable")
    monkeypatch.setattr(instruction.subprocess, "Popen", absent)
    assert instruction.ensure_ollama(wait_s=0.0) is False


# ---- #76 : modèle préchargé dès « iris instruction », pendant que l'utilisateur parle
def _wait(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.01)
    return cond()


def test_core_instruction_demande_le_prechargement():
    from motionzero.core import Core
    core = Core.__new__(Core)
    core._quiet = lambda: None
    core._start_open = lambda word, t, acts: acts.append(("open_start",))
    acts = []
    core._cmd_listen("instruction", 0.0, acts)
    assert acts == [("open_start",), ("instruction_warm",)]
    acts = []
    core._cmd_listen("rappel", 0.0, acts)          # les autres écoutes ne chargent rien
    assert acts == [("open_start",)]


def test_prechargement_appelle_le_modele():
    calls = []
    instr = Instructeur(lambda a: "", warm=lambda: calls.append(1) or True)
    instr.warm()
    assert _wait(lambda: calls == [1])


def test_prechargement_une_seule_fois_a_la_fois():
    import threading
    gate, calls = threading.Event(), []
    instr = Instructeur(lambda a: "", warm=lambda: calls.append(1) or gate.wait(2))
    instr.warm()
    assert _wait(lambda: calls == [1])
    instr.warm()                                    # le premier n'a pas fini : ignoré
    time.sleep(0.05)
    gate.set()
    assert calls == [1]


def test_prechargement_en_erreur_ne_bloque_pas_l_instruction():
    def boom():
        raise RuntimeError("ollama planté")
    instr = Instructeur(lambda a: "", warm=boom)
    instr.warm()
    assert _wait(lambda: not instr._warming.locked())
    instr.warm()                                    # le verrou a bien été rendu
    assert _wait(lambda: not instr._warming.locked())


def test_warm_local_sans_ollama(monkeypatch):
    from motionzero import instruction_base2 as b2
    monkeypatch.setattr(b2, "ensure_ollama", lambda: False)
    assert b2.warm_local() is False


def test_warm_local_modele_en_erreur(monkeypatch):
    from motionzero import instruction_base2 as b2
    monkeypatch.setattr(b2, "ensure_ollama", lambda: True)
    def http(*a, **k):
        raise OSError("refusé")
    monkeypatch.setattr(b2, "_http", http)
    assert b2.warm_local() is False


def test_warm_local_charge_le_modele_sans_question(monkeypatch):
    from motionzero import instruction_base2 as b2
    sent = []
    monkeypatch.setattr(b2, "ensure_ollama", lambda: True)
    monkeypatch.setattr(b2, "_http", lambda url, data=None, timeout=0: sent.append((url, data)) or {})
    assert b2.warm_local() is True
    url, data = sent[0]
    assert url.endswith("/api/generate") and data["model"] == b2.MODEL and "prompt" not in data
