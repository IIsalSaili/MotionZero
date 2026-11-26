"""La croix de l'accueil cache la fenêtre sans arrêter Iris ; « iris accueil » ou l'icône la rouvre."""
from motionzero.parametres import Param
from motionzero import vscode
from motionzero.app_outils import make_tray


def _win(tmp_path):
    from motionzero.ui import PreviewWindow, QApplication
    QApplication.instance() or QApplication([])
    return PreviewWindow(section_file=Param("s", str(tmp_path / "p.json")))


def test_croix_cache_sans_quitter(tmp_path):
    from PySide6.QtGui import QCloseEvent
    w = _win(tmp_path)
    w.show()
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert not ev.isAccepted() and not w.isVisible()
    w.reopen()
    assert w.isVisible() and not w.isMinimized()


def test_iris_accueil_passe_par_qt(monkeypatch):
    appels = []
    monkeypatch.setattr(vscode, "HOME_HOOK", lambda: appels.append(1))
    assert vscode.open_home() is None and appels == [1]


def test_iris_accueil_hook_en_panne(monkeypatch):
    def boom():
        raise RuntimeError("qt")
    monkeypatch.setattr(vscode, "HOME_HOOK", boom)
    monkeypatch.setattr(vscode.ctypes.windll.user32, "EnumWindows", lambda cb, l: 1, raising=False)
    assert vscode.open_home() == "APERCU INTROUVABLE"     # repli par Windows, sans planter


def test_icone_sans_logo():
    from motionzero.ui import QApplication
    qt = QApplication.instance() or QApplication([])
    assert make_tray(qt, lambda: None, path="introuvable.ico") is None
