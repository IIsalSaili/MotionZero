"""Micro de Claude : Iris suit son état réel (journal de l'extension) au lieu de basculer à l'aveugle (15/11)."""
import os
from motionzero import app, vscode
from motionzero.config import Config
from motionzero.core import Core

START = '[info] Received message from webview: {"type":"start_speech_to_text","channelId":"a"}\n'
STOP = '[info] Received message from webview: {"type":"stop_speech_to_text","channelId":"a"}\n'


def _log(tmp_path, text):
    d = tmp_path / "w" / "exthost"
    d.mkdir(parents=True)
    (d / "Claude VSCode.log").write_text(text, encoding="utf-8")
    return str(tmp_path / "w" / "exthost" / "Claude VSCode.log")


def test_etat_du_micro(tmp_path):
    assert vscode.claude_mic_state(_log(tmp_path, START)) is True
    assert vscode.claude_mic_state(_log(tmp_path / "b", START + STOP)) is False
    assert vscode.claude_mic_state(_log(tmp_path / "c", "rien\n")) is None          # journal sans dictée
    assert vscode.claude_mic_state(str(tmp_path / "absent" / "*.log")) is None      # pas de journal


def _run(monkeypatch, real, dictating):
    sent = []
    monkeypatch.setattr(vscode, "claude_mic_state", lambda *a: real)
    monkeypatch.setattr(vscode, "toggle_claude_dictation", lambda send: sent.append(1))
    class C:
        pass
    core = C()
    core.dictating, core.last_gesture = dictating, None
    class S:
        def play(self, *a):
            pass
    app.vscode_actions([("vscode_dictation",)], core, None, S(), 0.0)
    return sent


def test_raccourci_seulement_si_l_etat_differe(monkeypatch):
    assert _run(monkeypatch, real=False, dictating=False) == []   # Claude a déjà coupé : ne pas rallumer
    assert _run(monkeypatch, real=True, dictating=True) == []     # déjà allumé : ne pas éteindre
    assert _run(monkeypatch, real=True, dictating=False) == [1]   # couper
    assert _run(monkeypatch, real=None, dictating=False) == [1]   # état inconnu : bascule comme avant


def test_claude_coupe_seul_fin_de_dictee():
    core = Core(Config())
    acts = []
    core._cmd_claude("claude", 10.0, acts)
    assert core.dictating
    core.claude_mic_stopped(15.0)
    assert not core.dictating and core.confirming(15.5)            # « envoie / annule » attendus
    assert core.dictation_tick(30.0, 29.0) == []                    # plus de raccourci renvoyé ensuite
