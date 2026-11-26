"""Logo et nom d'Iris dans la barre des tâches."""
import os

from motionzero.app_outils import ICON_PATH, set_app_icon, set_app_identity


class Shell:
    def __init__(self, result=0, fail=False):
        self.result, self.fail, self.ids = result, fail, []

    def SetCurrentProcessExplicitAppUserModelID(self, app_id):
        if self.fail:
            raise OSError("refusé")
        self.ids.append(app_id)
        return self.result


def test_identite_donnee():
    sh = Shell()
    assert set_app_identity(shell32=sh) and sh.ids == ["Iris.motionzero"]


def test_identite_refusee_sans_planter():
    assert not set_app_identity(shell32=Shell(result=-1))
    assert not set_app_identity(shell32=Shell(fail=True))


def test_icone_presente():
    assert os.path.isfile(ICON_PATH)


class Qt:
    icon = None

    def setWindowIcon(self, icon):
        self.icon = icon


def test_icone_posee_ou_absente():
    qt = Qt()
    assert set_app_icon(qt) and qt.icon is not None
    qt2 = Qt()
    assert not set_app_icon(qt2, path="introuvable.ico") and qt2.icon is None
