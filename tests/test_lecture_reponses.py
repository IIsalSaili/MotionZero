"""Lecture à voix haute des réponses de « question » et du résultat d'« instruction »."""
from motionzero import ask
from motionzero.ask import Asker
from motionzero.instruction import Instructeur


class FakeSpeaker:
    def __init__(self, fail=False):
        self.said, self.fail = [], fail

    def say(self, text, force=False):
        if self.fail:
            raise RuntimeError("voix en panne")
        self.said.append((text, force))
        return True


def _asker(monkeypatch, question, answer="Paris."):
    a = Asker()
    monkeypatch.setattr(a, "_transcribe", lambda audio, sr: question)
    monkeypatch.setattr(ask, "answer_question", lambda q, **k: answer)
    return a


def test_reponse_lue(monkeypatch):
    a = _asker(monkeypatch, "capitale de la France")
    a.speaker = FakeSpeaker()
    a._work(b"", 16000)
    assert a.speaker.said == [("Paris.", True)]


def test_rien_entendu_lu(monkeypatch):
    a = _asker(monkeypatch, "")
    a.speaker = FakeSpeaker()
    a._work(b"", 16000)
    assert a.speaker.said == [("Je n'ai pas entendu de question.", True)]


def test_sans_voix_ni_panne(monkeypatch):
    a = _asker(monkeypatch, "capitale")
    a._work(b"", 16000)                       # pas de speaker : rien ne casse
    assert a.answer == "Paris."
    a.speaker = FakeSpeaker(fail=True)
    a._work(b"", 16000)                       # voix en panne : la réponse reste affichée
    assert a.phase == "answer" and a.answer == "Paris."


class FakeCore:
    last_gesture = None

    def confirming(self, t):
        return False


def test_instruction_impossible_et_faite_lues():
    ins = Instructeur(lambda audio: "")
    ins.speaker = FakeSpeaker()
    ins._think(b"")                           # rien entendu
    ins.events(FakeCore(), 0.0)
    ins._q.put(("done", True))
    ins.events(FakeCore(), 0.0)
    ins._q.put(("done", False))
    ins.events(FakeCore(), 0.0)
    textes = [t for t, _ in ins.speaker.said]
    assert textes == ["Instruction impossible : rien entendu", "Instruction faite", "Instruction interrompue"]


def test_instruction_voix_en_panne():
    ins = Instructeur(lambda audio: "")
    ins.speaker = FakeSpeaker(fail=True)
    ins._q.put(("done", True))
    ins.events(FakeCore(), 0.0)
    assert ins.title == "Instruction faite"
