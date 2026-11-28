"""L'overlay est remonté au-dessus de tout, sans planter si une fenêtre ou l'appel Windows échoue."""
from motionzero import ui_boutons


class Fen:
    def __init__(self, visible=True, hwnd=42, boom=False):
        self.visible, self.hwnd, self.boom = visible, hwnd, boom

    def isVisible(self):
        if self.boom:
            raise RuntimeError("fenetre detruite")
        return self.visible

    def winId(self):
        return self.hwnd


def test_remonte_les_fenetres_visibles(monkeypatch):
    appels = []
    monkeypatch.setattr(ui_boutons._u32, "SetWindowPos", lambda h, after, *a: appels.append((h.value, after.value, a[-1])) or 1, raising=False)
    assert ui_boutons.raise_topmost([Fen(hwnd=1), Fen(visible=False, hwnd=2), Fen(hwnd=3)]) == 2
    assert [a[0] for a in appels] == [1, 3]
    assert all(a[1] in (-1, 0xFFFFFFFFFFFFFFFF) for a in appels)
    assert all(a[2] & 0x0010 for a in appels)          # jamais d'activation (le focus reste à l'appli)


def test_echecs_ignores(monkeypatch):
    monkeypatch.setattr(ui_boutons._u32, "SetWindowPos", lambda *a: 0, raising=False)
    assert ui_boutons.raise_topmost([Fen(), Fen(boom=True)]) == 0

    def refuse(*a):
        raise OSError("refuse")
    monkeypatch.setattr(ui_boutons._u32, "SetWindowPos", refuse, raising=False)
    assert ui_boutons.raise_topmost([Fen()]) == 0
