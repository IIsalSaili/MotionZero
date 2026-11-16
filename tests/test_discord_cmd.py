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
    assert parse(text) == (word, None)


@pytest.mark.parametrize("text, error", [
    ("", "message_vide"), (None, "message_vide"), ("iris", "message_vide"), ("!!!", "message_vide"),
    ("iris stop", "refuse_a_distance"), ("ouvre spotify", "pas_encore_par_ecrit"),
    ("iris ouvre", "pas_encore_par_ecrit"), ("question", "pas_encore_par_ecrit"),
    ("bonjour toi", "commande_inconnue"),
])
def test_parse_echecs(text, error):
    word, err = parse(text)
    assert word is None and err[0] == error


def test_parse_suggestions():
    assert "studio" in parse("studoi")[1][1]


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
