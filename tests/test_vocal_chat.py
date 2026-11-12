"""Bot vocal temporaire : « iris viens / pars / parle », Haiku, mentions. Sans Discord ni Haiku réels."""
import queue

from motionzero.config import Config
from motionzero.core import Core
from motionzero.vocal_chat import PERSONA, Chat, chat_spoken, chat_turn


class FakeBot:
    connected = was_connected = True

    def __init__(self, ok=True):
        self.sent, self.ok, self.kinds, self.inbox, self._req = [], ok, {}, queue.Queue(), 0

    def send(self, msg):
        if not self.ok:
            return None
        self._req += 1
        self.kinds[self._req] = msg["t"]
        self.sent.append(msg)
        return self._req


def test_reponse_avec_le_fil():
    seen = []

    def ask(q, system):
        seen.append((q, system))
        return " Pas mal ! "
    chat = Chat(ask)
    assert chat.reply("Tom", "salut") == "Pas mal !"
    chat.reply("Tom", "et toi ?")
    assert "Tom : salut" in seen[1][0] and "Iris : Pas mal !" in seen[1][0] and seen[0][1] == PERSONA


def test_tour_complet_le_bot_parle():
    bot, msgs = FakeBot(), []
    chat_turn(Chat(lambda q, system: "Coucou"), bot, msgs.append, "Tom", "salut")
    assert bot.sent == [{"t": "say", "text": "Coucou"}] and msgs == ["IRIS : Coucou"]


def test_haiku_en_panne():
    def boom(q, system):
        raise RuntimeError("hors ligne")
    bot, msgs = FakeBot(), []
    chat_turn(Chat(boom), bot, msgs.append, "Tom", "salut")
    assert bot.sent == [] and "INDISPONIBLE" in msgs[0]


def test_reponse_vide_refusee():
    bot, msgs = FakeBot(), []
    chat_turn(Chat(lambda q, system: "  "), bot, msgs.append, "Tom", "salut")
    assert bot.sent == [] and "INDISPONIBLE" in msgs[0]


def test_bot_absent():
    msgs = []
    chat_turn(Chat(lambda q, system: "Coucou"), FakeBot(ok=False), msgs.append, "Tom", "salut")
    assert msgs == ["BOT DISCORD ABSENT"]


def test_rien_entendu():
    bot, msgs = FakeBot(), []
    chat_spoken(b"a", lambda a: "", Chat(lambda q, system: "x"), bot, msgs.append)
    assert msgs == ["RIEN ENTENDU"] and bot.sent == []


def test_iris_viens_pars_parle():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("viens", 1.2) == [("bot_join",)]
    core.voice("iris", 2.0)
    assert core.voice("pars", 2.2) == [("bot_leave",)]
    core.voice("iris", 3.0)
    assert core.voice("parle", 3.2) == [("open_start",)] and core.opening
    assert core.open_tick(6.0, last_speech_t=4.0) == [("parle_stop",)]


def test_sans_iris_rien():
    core = Core(Config())
    assert core.voice("viens", 1.0) == [] and core.voice("parle", 1.5) == []


def test_mention_en_vocal_fait_repondre(monkeypatch):
    from motionzero import app
    from motionzero.vocal_chat import STATE
    started = []
    monkeypatch.setattr(app.threading, "Thread",
                        lambda target, name, daemon, args: type("T", (), {"start": lambda s: started.append(args)})())
    core, bot = Core(Config()), FakeBot()
    req = bot.send({"t": "join"})
    bot.inbox.put({"t": "result", "req": req, "ok": True, "channel": "Général"})
    app.bot_events(bot, core, None, {"mute": False, "deaf": False}, 1.0, on_message=lambda m: None)
    assert STATE["in_voice"] and "GÉNÉRAL" in core.last_gesture[0]
    bot.inbox.put({"t": "message", "mention": True, "author": "Tom", "content": "@Iris raconte une blague"})
    app.bot_events(bot, core, None, {"mute": False, "deaf": False}, 2.0, on_message=lambda m: None)
    assert started and started[0][3] == "Tom"
    bot.inbox.put({"t": "link", "connected": False})
    app.bot_events(bot, core, None, {"mute": False, "deaf": False}, 3.0, on_message=lambda m: None)
    assert not STATE["in_voice"]
