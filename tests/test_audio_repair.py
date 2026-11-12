"""Réparer le son (bouton en bas à gauche) : tous les chemins, sans toucher aux vrais services Windows."""
from motionzero import audio_repair as ar


class Done:
    def __init__(self, code=0, out=""):
        self.returncode, self.stdout = code, out


def fake(monkeypatch, *, elevate_code=0, running_after=1):
    calls = {"elevate": 0, "sc": 0}

    def run(args, timeout=20):
        if args[0] == "powershell":
            calls["elevate"] += 1
            assert "RunAs" in args[-1] and "Audiosrv" in args[-1]
            return Done(elevate_code)
        if args[0] == "sc":
            calls["sc"] += 1
            return Done(0, "STATE : 4 RUNNING" if running_after and calls["sc"] >= running_after else "STOPPED")
        raise AssertionError(args)
    monkeypatch.setattr(ar, "_run", run)
    return calls


def go(reopen=lambda: None, heard=lambda t: True):
    return ar.repair(reopen, heard, wait=lambda s: None, clock=lambda: 0.0)


def test_succes(monkeypatch):
    calls = fake(monkeypatch, running_after=3)
    opened = []
    assert go(reopen=lambda: opened.append(1)) == "SON REPARE"
    assert calls["elevate"] == 1 and opened == [1]


def test_non_sur_la_fenetre_windows(monkeypatch):
    fake(monkeypatch, elevate_code=5)
    opened = []
    assert go(reopen=lambda: opened.append(1)) == "REPARATION DU SON ANNULEE" and opened == []


def test_service_ne_repart_pas(monkeypatch):
    fake(monkeypatch, running_after=0)
    assert go() == "SERVICE AUDIO NON REDEMARRE"


def test_micro_non_rouvert(monkeypatch):
    fake(monkeypatch)

    def boom():
        raise OSError("aucun micro")
    assert go(reopen=boom) == "MICRO NON ROUVERT : relance Iris"


def test_micro_toujours_muet(monkeypatch):
    fake(monkeypatch)
    assert go(heard=lambda t: False) == "MICRO TOUJOURS MUET"


def test_windows_injoignable(monkeypatch):
    def run(args, timeout=20):
        raise OSError("powershell absent")
    monkeypatch.setattr(ar, "_run", run)
    assert go() == "REPARATION DU SON : ECHEC DU LANCEMENT"


def test_le_micro_signale_le_son_recu():
    import queue
    from motionzero.voice import VoiceListener
    v = VoiceListener.__new__(VoiceListener)
    v.audio = queue.Queue(maxsize=2)
    v.last_block_t = -1e9
    assert not v.heard_since(0.0)
    v._callback(b"\x00\x00" * 10, 10, None, None)                         # même du silence compte
    assert v.heard_since(0.0)
