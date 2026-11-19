"""Commandes d'Iris écrites en MP au bot Discord (#43) : lecture du texte, exécution, réponse au bot."""
import pytest

from motionzero import app
from motionzero.config import Config
from motionzero.core import Core
from motionzero.discord_cmd import WAIT_S, Pending, parse
from test_discord_link import FakeLink


@pytest.mark.parametrize("text, word", [
    ("iris studio", "studio"), ("Studio", "studio"), ("IRIS, Studio !", "studio"),
    ("  iris   plein   écran ", "plein écran"), ("double clic", "double"), ("reprise", "reprise"),
])
def test_parse_ok(text, word):
    assert parse(text) == (word, None, None)


@pytest.mark.parametrize("text, error", [
    ("", "message_vide"), (None, "message_vide"), ("iris", "message_vide"), ("!!!", "message_vide"),
    ("iris stop", "refuse_a_distance"), ("iris ouvre", "phrase_manquante"), ("question", "phrase_manquante"),
    ("bonjour toi", "commande_inconnue"),
])
def test_parse_echecs(text, error):
    word, phrase, err = parse(text)
    assert word is None and phrase is None and err[0] == error


def test_parse_suggestions():
    assert "studio" in parse("studoi")[2][1]


@pytest.mark.parametrize("text, word, phrase", [
    ("ouvre spotify", "ouvre", "spotify"), ("Iris, timer 10 minutes", "timer", "10 minutes"),
    ("message dans général, Salut !", "message", "dans général, Salut !"), ("timer", "timer", None),
    ("iris ferme", "ferme", None), ("claude corrige le test", "claude", "corrige le test"),
])
def test_parse_phrase(text, word, phrase):
    assert parse(text) == (word, phrase, None)


def run(link, core, text, t=100.0):
    link.inbox.put({"t": "command", "id": 5, "text": text})
    return app.bot_events(link, core, None, {"mute": False, "deaf": False}, t)


def test_commande_executee_puis_reponse():
    core, link = Core(Config()), FakeLink()
    acts = run(link, core, "iris studio")
    assert ("open_app", "studio") in acts and link.sent == []        # attend l'effet avant de répondre
    app.bot_events(link, core, None, {}, 100.0 + WAIT_S)
    assert link.sent[-1]["t"] == "command_result" and link.sent[-1]["ok"] and link.sent[-1]["id"] == 5
    assert link.pending_cmds == []


def test_commande_laisse_l_ecoute_fermee():
    core, link = Core(Config()), FakeLink()
    run(link, core, "studio")
    assert not core.listening(100.5)


def test_echec_dans_l_ile_renvoye():
    core, link = Core(Config()), FakeLink()
    run(link, core, "studio")
    core.last_gesture = ("VS CODE INTROUVABLE", 100.2)
    app.bot_events(link, core, None, {}, 100.3)
    assert link.sent[-1]["ok"] is False and "INTROUVABLE" in link.sent[-1]["text"]


def test_commande_refusee_repond_tout_de_suite():
    core, link = Core(Config()), FakeLink()
    assert run(link, core, "stop") == []
    assert link.sent[-1]["ok"] is False and link.pending_cmds == []


def test_exception_dans_core(monkeypatch):
    core, link = Core(Config()), FakeLink()
    monkeypatch.setattr(core, "voice", lambda *a, **k: 1 / 0)
    assert run(link, core, "studio") == []
    assert link.sent[-1]["ok"] is False and "Erreur" in link.sent[-1]["text"]


def test_commande_pendant_la_dictee_ignoree():
    core, link = Core(Config()), FakeLink()
    core.dictating = True
    run(link, core, "studio")
    assert link.sent[-1]["ok"] is False and link.pending_cmds == []


def test_pending_sans_changement():
    p = Pending(1, "copie", ("avant", 0), 0.0)
    assert p.reply(p.before, 0.1) is None
    assert p.reply(p.before, WAIT_S)["text"] == "« copie » : fait"


class FakeListener:
    def __init__(self):
        self.typed, self.capture = None, None

    def stop_capture(self):
        from motionzero.voice import VoiceListener as Listener
        return Listener.stop_capture(self)


def run_l(link, core, listener, text, t=100.0):
    link.inbox.put({"t": "command", "id": 5, "text": text})
    return app.bot_events(link, core, None, {}, t, listener)


@pytest.mark.parametrize("text, start, stop", [
    ("ouvre spotify", "open_start", "open_stop"), ("timer 10 minutes", "open_start", "timer_stop"),
    ("rappel dans 10 minutes pâtes", "open_start", "rappel_stop"), ("question quelle heure", "ask_start", "ask_stop"),
    ("type bonjour", "type_start", "type_stop"), ("message dans général, salut", "open_start", "message_stop"),
    ("volume 40", "open_start", "volume_stop"), ("salon jeux", "open_start", "salon_stop"),
])
def test_phrase_remplace_le_micro(text, start, stop):
    core, link, lis = Core(Config()), FakeLink(), FakeListener()
    names = [a[0] for a in run_l(link, core, lis, text)]
    assert names.index(start) < names.index(stop)        # capture ouverte puis fermée dans la même image
    assert lis.stop_capture() == text.split(None, 1)[1]  # le texte du MP à la place du son
    assert lis.stop_capture() == b""                     # une seule fois : la voix suivante enregistre
    assert not (core.opening or core.asking or core.typing) and not core.listening(100.5)


def test_claude_avec_texte_tape_dans_vs_code():
    core, link, lis = Core(Config()), FakeLink(), FakeListener()
    acts = run_l(link, core, lis, "claude corrige le test")
    names = [a[0] for a in acts]
    assert ("open_app", "studio") in acts and names.index("type_stop") > names.index("open_app")
    assert lis.typed == "corrige le test"


def test_phrase_sans_micro():
    core, link = Core(Config()), FakeLink()
    assert run_l(link, core, None, "ouvre spotify") == []
    assert link.sent[-1]["ok"] is False and "sans la voix" in link.sent[-1]["text"]


def test_phrase_inutilisee_effacee():
    core, link, lis = Core(Config()), FakeLink(), FakeListener()
    core.timer_running = True                            # « timer » annule celui en cours : pas d'écoute
    run_l(link, core, lis, "timer 5 minutes")
    assert lis.typed is None


def test_phrase_manquante_exemple():
    core, link = Core(Config()), FakeLink()
    run_l(link, core, FakeListener(), "ouvre")
    assert "ouvre spotify" in link.sent[-1]["text"]


def test_transcription_sautee():
    from motionzero.ask import Asker
    assert Asker._transcribe(None, "spotify", 16000) == "spotify"


@pytest.mark.parametrize("word, kind, ok, error, expect_ok, part", [
    ("viens", "join", True, None, True, "EN VOCAL"),
    ("viens", "join", False, "pas_en_vocal", False, "PAS EN VOCAL"),        # pas un « échec » de l'île : vu quand même
    ("pars", "leave", True, None, True, "QUITTE"),
])
def test_vocal_reponse_du_bot(word, kind, ok, error, expect_ok, part):
    core, link = Core(Config()), FakeLink()
    acts = run(link, core, word)
    assert acts and link.sent == []
    link.kinds[9] = kind
    link.inbox.put({"t": "result", "req": 9, "ok": ok, "error": error, "channel": "Jeux"})
    app.bot_events(link, core, None, {}, 103.0)                 # bien après WAIT_S : on attendait le bot
    app.bot_events(link, core, None, {}, 103.1)
    r = link.sent[-1]
    assert r["t"] == "command_result" and r["ok"] is expect_ok and part in r["text"].upper()


def test_vocal_bot_muet():
    from motionzero.discord_cmd import WAIT_BOT_S
    core, link = Core(Config()), FakeLink()
    run(link, core, "viens")
    app.bot_events(link, core, None, {}, 100.0 + WAIT_S + 1)
    assert link.sent == []                                     # pas de faux « fait » avant la réponse du bot
    app.bot_events(link, core, None, {}, 100.0 + WAIT_BOT_S)
    assert link.sent[-1]["ok"] is False and "pas répondu" in link.sent[-1]["text"]


def test_message_par_mp_reponse_du_bot():
    core, link, lis = Core(Config()), FakeLink(), FakeListener()
    run_l(link, core, lis, "message dans général, salut")
    link.kinds[3] = "send"
    link.inbox.put({"t": "result", "req": 3, "ok": True, "channel": "général"})
    app.bot_events(link, core, None, {}, 101.0)
    app.bot_events(link, core, None, {}, 101.1)
    assert link.sent[-1]["ok"] and "GÉNÉRAL" in link.sent[-1]["text"].upper()


@pytest.mark.parametrize("word, act", [("mute", "discord_mute"), ("démute", "discord_unmute"),
                                       ("sourdine", "discord_deafen"), ("silence", "discord_hush"), ("lis", "discord_read")])
def test_commandes_discord_locales(word, act):
    core, link = Core(Config()), FakeLink()
    assert (act,) in run(link, core, word)
