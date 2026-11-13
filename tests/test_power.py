"""« iris réveil » / « iris wake » rallume l'écran ; surveillance de la boucle."""
import threading

from motionzero.config import Config
from motionzero.core import Core
from motionzero.power import ES_DISPLAY_REQUIRED, power_actions, wake_screen


class Fake:
    def __init__(self, ret=1, boom=False):
        self.calls, self.ret, self.boom = [], ret, boom

    def SetThreadExecutionState(self, flags):
        if self.boom:
            raise OSError("refuse")
        self.calls.append(("state", flags))
        return self.ret

    def mouse_event(self, *a):
        self.calls.append(("mouse", a))


def test_reveil_rallume_l_ecran_sans_bloquer_la_veille():
    k, u = Fake(), Fake()
    assert wake_screen(k, u)
    assert k.calls == [("state", ES_DISPLAY_REQUIRED)]     # ponctuel, jamais ES_CONTINUOUS ni ES_SYSTEM_REQUIRED
    assert [c for c in u.calls if c[0] == "mouse"]
    assert not wake_screen(Fake(boom=True), u)


def test_iris_reveil_et_iris_wake():
    for mot in ("réveil", "wake"):
        core = Core(Config())
        core.voice("iris", 0.0)
        assert ("wake",) in core.voice(mot, 0.2)


def test_reveil_sans_iris_ignore():
    core = Core(Config())
    assert ("wake",) not in core.voice("réveil", 0.2)


def test_power_actions_ne_garde_que_le_reste():
    seen = []
    assert power_actions([("wake",), ("click", "left")], wake=lambda: seen.append(1)) == [("click", "left")]
    assert seen == [1]


def test_surveillance_ecrit_les_piles_si_la_boucle_bloque(tmp_path):
    from motionzero.app import watch_engine
    now = [100.0]
    live, stop = {"beat": 50.0}, threading.Event()
    ticks = iter(range(3))

    def wait(_):
        return next(ticks, None) is None                   # 3 tours puis arrêt
    path = tmp_path / "blocage.txt"
    watch_engine(live, stop, str(path), clock=lambda: now[0], wait=wait)
    txt = path.read_text(encoding="utf-8")
    assert txt.count("bloquee") == 1 and "watch_engine" in txt   # une seule fois par blocage


def test_surveillance_muette_si_la_boucle_tourne(tmp_path):
    from motionzero.app import watch_engine
    ticks = iter(range(3))
    path = tmp_path / "blocage.txt"
    watch_engine({"beat": 99.0}, threading.Event(), str(path), clock=lambda: 100.0,
                 wait=lambda _: next(ticks, None) is None)
    assert not path.exists()
