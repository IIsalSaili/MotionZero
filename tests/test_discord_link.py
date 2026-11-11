"""Liaison avec le bot Discord (issue #19) : connexion, échecs, lecture à voix haute, commandes vocales."""
import json
import queue
import socket
import threading
import time

import pytest

from motionzero import app
from motionzero.config import Config
from motionzero.core import Core
from motionzero.discord_link import BotLink, read_bot_config, result_label, speech_for
from motionzero.speech import Speaker

SECRET = "s" * 32


def write_conf(tmp_path, port, secret=SECRET):
    (tmp_path / "config.json").write_text(json.dumps({"port": port, "ipc_secret": secret}), encoding="utf-8")


class FakeBot:
    """Faux bot : accepte une connexion, vérifie le secret, enregistre ce qu'il reçoit."""

    def __init__(self, reply_hello=True):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen()
        self.port = self.srv.getsockname()[1]
        self.got = queue.Queue()
        self.conn = None
        self.reply_hello = reply_hello
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.conn, _ = self.srv.accept()
        f = self.conn.makefile("rb")
        for line in f:
            msg = json.loads(line)
            self.got.put(msg)
            if msg["t"] == "hello" and self.reply_hello:
                ok = msg["token"] == SECRET
                self.send({"t": "hello", "ok": True} if ok else {"t": "result", "ok": False, "error": "secret_refuse"})

    def send(self, msg):
        self.conn.sendall(json.dumps(msg).encode() + b"\n")

    def next(self, t, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            msg = self.got.get(timeout=timeout)
            if msg["t"] == t:
                return msg
        raise AssertionError(t)


def wait(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_config_du_bot(tmp_path):
    assert read_bot_config(tmp_path) is None                       # absent
    (tmp_path / "config.json").write_text("{", encoding="utf-8")
    assert read_bot_config(tmp_path) is None                       # illisible
    write_conf(tmp_path, 1234, secret="court")
    assert read_bot_config(tmp_path) is None                       # secret trop court
    write_conf(tmp_path, 1234)
    assert read_bot_config(tmp_path) == (1234, SECRET)


def test_bot_absent_liaison_eteinte(tmp_path):
    link = BotLink(str(tmp_path), launch=False).start()
    assert not link.enabled
    assert link.send({"t": "send", "text": "x"}) is None
    link.bye()                                                      # ne plante pas


def test_connexion_envoi_reception_bye(tmp_path):
    fake = FakeBot()
    write_conf(tmp_path, fake.port)
    link = BotLink(str(tmp_path), launch=False).start()
    assert fake.next("hello")["token"] == SECRET
    assert wait(lambda: link.connected)
    req = link.send({"t": "send", "text": "général salut"})
    assert fake.next("send") == {"t": "send", "text": "général salut", "req": req}
    assert link.kinds[req] == "send"
    fake.send({"t": "message", "author": "Bob", "content": "yo"})
    assert wait(lambda: any(m.get("t") == "message" for m in list(link.inbox.queue)))
    link.bye()
    assert fake.next("bye")


def test_secret_refuse(tmp_path):
    fake = FakeBot()
    write_conf(tmp_path, fake.port, secret="m" * 20)
    link = BotLink(str(tmp_path), launch=False).start()
    fake.next("hello")
    time.sleep(0.3)
    assert not link.connected
    link.bye()


def test_bot_muet_abandon(tmp_path, monkeypatch):
    fake = FakeBot(reply_hello=False)
    write_conf(tmp_path, fake.port)
    t = [0.0]
    link = BotLink(str(tmp_path), launch=False, clock=lambda: t[0]).start()
    fake.next("hello")
    t[0] = 10                                                       # 5 s sans réponse dépassées
    assert wait(lambda: not fake.got.empty() or True)
    time.sleep(1.5)
    assert not link.connected
    link.bye()


def test_bot_injoignable_lancement_freine(tmp_path, monkeypatch):
    write_conf(tmp_path, 1)
    launched = []
    monkeypatch.setattr("motionzero.discord_link.subprocess.Popen", lambda *a, **k: launched.append(a))
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "pythonw.exe").write_text("")
    t = [100.0]
    link = BotLink(str(tmp_path), clock=lambda: t[0])
    link._maybe_launch()
    link._maybe_launch()                                            # moins d'une minute : pas relancé
    assert len(launched) == 1
    t[0] += 61
    link._maybe_launch()
    assert len(launched) == 2


def test_lancement_sans_venv(tmp_path):
    write_conf(tmp_path, 1)
    BotLink(str(tmp_path))._maybe_launch()                          # pas de pythonw : rien, sans planter


def test_file_pleine_jette_le_plus_vieux(tmp_path):
    link = BotLink(str(tmp_path), launch=False)
    for i in range(250):
        link._put({"t": "message", "n": i})
    assert link.inbox.qsize() == 200 and link.inbox.queue[-1]["n"] == 249


def test_libelles():
    assert result_label({"ok": True, "channel": "général"}) == "DISCORD : ENVOYE DANS #GÉNÉRAL"
    assert result_label({"ok": True, "channel": "Jeux"}, "move") == "DISCORD : SALON JEUX"
    assert result_label({"ok": False, "error": "salon_inconnu", "suggestions": ["musique"]}) == "SALON INCONNU (MUSIQUE ?)"
    assert result_label({"ok": False, "error": "bizarre"}) == "DISCORD : ERREUR BIZARRE"
    assert speech_for({"author": "Bob", "dm": True, "content": "salut"}) == "Bob, en privé : salut"
    assert speech_for({"author": "Bob", "channel": "général", "content": "yo"}) == "Bob, dans général : yo"


class FakeVoice:
    def __init__(self):
        self.said = []

    def Speak(self, text, flags):
        self.said.append(text)

    def WaitUntilDone(self, ms):
        return True


def test_lecture_a_voix_haute():
    v = FakeVoice()
    s = Speaker(factory=lambda rate: v)
    assert s.say("bonjour")
    assert wait(lambda: v.said == ["bonjour"])
    assert not s.say("")
    s.say("mot " * 200)
    assert wait(lambda: len(v.said) == 2) and v.said[1].endswith("la suite à l'écran")
    s.enabled = False
    assert not s.say("coupé")


def test_voix_windows_absente():
    def boom(rate):
        raise OSError("pas de SAPI")
    s = Speaker(factory=boom)
    assert wait(lambda: not s.ok)
    assert not s.say("rien")


def heard(core, *words, t=10.0):
    acts = []
    for i, w in enumerate(words):
        acts += core.voice(w, t + i * 0.5)
    return acts


def test_iris_message_puis_silence():
    core = Core(Config())
    assert heard(core, "iris", "message") == [("open_start",)]
    assert core.opening and core.open_kind == "message"
    assert core.open_tick(12.0, 11.5) == []                         # parle encore
    acts = core.open_tick(20.0, 12.0)
    assert acts == [("message_stop",)] and not core.opening


def test_iris_salon_rien_dit():
    core = Core(Config())
    heard(core, "iris", "salon")
    assert core.open_tick(30.0, 0.0) == [("open_cancel",)]
    assert core.last_gesture[0] == "RIEN ENTENDU : salon annule"


def test_iris_silence_et_lis():
    core = Core(Config())
    assert heard(core, "iris", "silence") == [("discord_hush",)]
    assert heard(core, "iris", "lis", t=20.0) == [("discord_read",)]
    v = FakeVoice()
    s = Speaker(factory=lambda rate: v)
    assert app.discord_actions([("discord_hush",), ("click", "left")], s) == [("click", "left")]
    assert not s.enabled
    app.discord_actions([("discord_read",)], s)
    assert s.enabled
    assert app.discord_actions([("discord_hush",)], None) == []   # bot absent : sans planter


class FakeAsker:
    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    def _transcribe(self, audio, sr):
        if self.exc:
            raise self.exc
        return self.text


class FakeLink:
    def __init__(self, connected=True, accept=True):
        self.connected, self.accept, self.sent = connected, accept, []
        self.inbox = queue.Queue()
        self.kinds = {}
        self.was_connected = True

    def send(self, msg):
        self.sent.append(msg)
        return 1 if self.accept else None


@pytest.mark.parametrize("asker, link, expected", [
    (FakeAsker(""), FakeLink(), "RIEN ENTENDU"),
    (FakeAsker(exc=RuntimeError("gpu")), FakeLink(), "RIEN ENTENDU"),
    (FakeAsker("général salut"), FakeLink(connected=False), "BOT DISCORD ABSENT"),
    (FakeAsker("général salut"), None, "BOT DISCORD ABSENT"),
    (FakeAsker("général salut"), FakeLink(accept=False), "BOT DISCORD OCCUPE"),
])
def test_dictee_discord_echecs(asker, link, expected):
    msgs = []
    app.discord_spoken("message_stop", b"", asker, link, msgs.append)
    assert msgs == [expected]


def test_dictee_discord_ok():
    link, msgs = FakeLink(), []
    app.discord_spoken("message_stop", b"", FakeAsker("Dans général, salut."), link, msgs.append)
    app.discord_spoken("salon_stop", b"", FakeAsker("Jeux."), link, msgs.append)
    assert msgs == [] and link.sent == [{"t": "send", "text": "Dans général, salut"},
                                         {"t": "move", "channel": "Jeux"}]


def test_evenements_du_bot():
    core, link = Core(Config()), FakeLink()
    v = FakeVoice()
    s = Speaker(factory=lambda rate: v)
    dv = {"mute": False, "deaf": False}
    link.kinds[7] = "move"
    for m in ({"t": "message", "author": "Bob", "channel": "général", "content": "yo"},
              {"t": "voice_state", "self_mute": True, "self_deaf": False},
              {"t": "result", "req": 7, "ok": False, "error": "pas_en_vocal"},
              {"t": "inconnu"}):
        link.inbox.put(m)
    app.bot_events(link, core, s, dv, 1.0)
    assert dv == {"mute": True, "deaf": False}
    assert core.last_gesture[0] == "TU N'ES PAS EN VOCAL"
    assert ("Bob : yo", 1.0) in core.feed
    assert wait(lambda: v.said == ["Bob, dans général : yo"])
    link.inbox.put({"t": "link", "connected": False})
    app.bot_events(link, core, None, dv, 2.0)                       # sans voix : sans planter
    assert core.last_gesture[0] == "BOT DISCORD DECONNECTE"
