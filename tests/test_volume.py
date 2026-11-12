"""« iris volume » : phrase -> réglage du volume de Windows. Sans carte son (faux appareil)."""
import pytest

from motionzero.config import Config
from motionzero.core import Core
from motionzero.volume import parse_volume, volume_spoken


@pytest.mark.parametrize("text,cmd", [
    ("40", ("set", 40)), ("40 %", ("set", 40)), ("Mets à 25.", ("set", 25)), ("cinquante", ("set", 50)),
    ("soixante-dix", ("set", 70)), ("quatre-vingt", ("set", 80)), ("quatre-vingt-dix", ("set", 90)),
    ("cent", ("set", 100)), ("150", ("set", 100)), ("à fond", ("set", 100)), ("zéro", ("set", 0)),
    ("Plus fort.", ("delta", 10)), ("monte", ("delta", 10)), ("moins fort", ("delta", -10)), ("baisse un peu", ("delta", -10)),
    ("baisse à 30", ("set", 30)), ("Coupe le son.", ("mute",)), ("muet", ("mute",)), ("remets le son", ("unmute",)),
])
def test_phrases_comprises(text, cmd):
    assert parse_volume(text) == cmd


@pytest.mark.parametrize("text", ["", "   ", "bonjour", "quelle heure est-il"])
def test_phrases_incomprises(text):
    assert parse_volume(text) is None


class FakeDevice:
    def __init__(self, fail=False):
        self.cmds, self.fail = [], fail

    def apply(self, cmd):
        if self.fail:
            raise OSError("pas de carte son")
        self.cmds.append(cmd)
        return "VOLUME OK"


def _run(text, device=None, transcribe=None):
    msgs = []
    volume_spoken(b"audio", transcribe or (lambda a: text), msgs.append, device or FakeDevice())
    return msgs


def test_reglage_applique():
    dev = FakeDevice()
    assert _run("30", dev) == ["VOLUME OK"] and dev.cmds == [("set", 30)]


def test_rien_entendu():
    dev = FakeDevice()
    assert "RIEN ENTENDU" in _run("", dev)[0] and dev.cmds == []


def test_phrase_incomprise():
    dev = FakeDevice()
    assert "pas compris" in _run("bonjour", dev)[0] and dev.cmds == []


def test_transcription_en_panne():
    def boom(a):
        raise RuntimeError("whisper absent")
    assert "RIEN ENTENDU" in _run("", transcribe=boom)[0]


def test_carte_son_en_panne():
    assert "impossible" in _run("30", FakeDevice(fail=True))[0]


def test_iris_volume_ecoute_puis_s_arrete_au_silence():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("volume", 1.5)[0] == ("open_start",) and core.opening
    acts = core.open_tick(4.0, last_speech_t=2.5)
    assert acts == [("volume_stop",)] and not core.opening


def test_iris_volume_sans_parole_annule():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("volume", 1.5)
    acts = core.open_tick(30.0, last_speech_t=0.0)
    assert acts == [("open_cancel",)] and "volume" in core.last_gesture[0].lower()


def test_volume_sans_iris_ne_fait_rien():
    core = Core(Config())
    assert core.voice("volume", 1.0) == [] and not core.opening


def test_barre_visible_pendant_l_ecoute_puis_4_s():
    from motionzero.volume import VolumeView
    v = VolumeView()
    assert v.state(0.0, listening=True) is None          # volume pas encore lu : rien
    v.show(74, False, now=10.0)
    assert v.state(11.0) == {"level": 74, "muted": False}
    assert v.state(15.0) is None                          # 4 s après le réglage : disparue
    assert v.state(15.0, listening=True) == {"level": 74, "muted": False}


def test_lecture_du_volume_a_l_ouverture():
    from motionzero.volume import VolumeView, volume_peek

    class Dev:
        def read(self):
            return 42, True
    v = VolumeView()
    volume_peek(Dev(), v)
    assert v.state(v.until - 1) == {"level": 42, "muted": True}


def test_lecture_en_panne_ne_plante_pas():
    from motionzero.volume import VolumeView, volume_peek

    class Dev:
        def read(self):
            raise OSError("pas de carte son")
    v = VolumeView()
    volume_peek(Dev(), v)
    assert v.level is None


def test_iris_volume_demande_la_barre():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert ("volume_show",) in core.voice("volume", 1.5)


def test_jauge():
    from motionzero.ui import volume_fill
    assert volume_fill(0, 200) == 0 and volume_fill(50, 200) == 100 and volume_fill(120, 200) == 200
