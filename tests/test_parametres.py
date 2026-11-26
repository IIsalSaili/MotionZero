"""Un seul fichier de réglages (parametres.json) ; reprise des anciens fichiers .txt d'un seul choix."""
import json

from motionzero import parametres as pm
from motionzero.parametres import Param, migrate


def test_lecture_ecriture_et_cles_separees(tmp_path):
    f = str(tmp_path / "p.json")
    a, b = Param("a", f), Param("b", f)
    assert a.read() is None
    assert a.write("oui") and b.write(0.7)
    assert a.read() == "oui" and b.read() == "0.7"
    assert json.loads(open(f, encoding="utf-8").read()) == {"a": "oui", "b": "0.7"}


def test_fichier_illisible_ou_pas_un_objet(tmp_path):
    f = tmp_path / "p.json"
    f.write_text("{pas du json", encoding="utf-8")
    assert Param("a", str(f)).read() is None
    assert Param("a", str(f)).write("x") and Param("a", str(f)).read() == "x"   # réécrit proprement
    f.write_text("[1, 2]", encoding="utf-8")
    assert Param("a", str(f)).read() is None


def test_ecriture_impossible_sans_exception(tmp_path):
    assert Param("a", str(tmp_path / "absent" / "p.json")).write("x") is False


def test_reprise_des_anciens_fichiers(tmp_path):
    (tmp_path / "lecture.txt").write_text("oui\n", encoding="utf-8")
    (tmp_path / "pointeur.txt").write_text("tete", encoding="utf-8")
    (tmp_path / "volume_iris.txt").write_text("0.3", encoding="utf-8")
    f = str(tmp_path / "p.json")
    Param("volume", f).write("0.9")                      # déjà dans le JSON : gagne
    assert sorted(migrate(f, str(tmp_path))) == ["lecture", "pointeur"]
    assert Param("lecture", f).read() == "oui" and Param("pointeur", f).read() == "tete"
    assert Param("volume", f).read() == "0.9"
    assert not any((tmp_path / n).exists() for n in pm.LEGACY.values())   # anciens fichiers supprimés


def test_reprise_sans_ancien_fichier(tmp_path):
    f = tmp_path / "p.json"
    assert migrate(str(f), str(tmp_path)) == [] and not f.exists()


def test_reprise_impossible_garde_les_anciens(tmp_path):
    (tmp_path / "quota.txt").write_text("oui", encoding="utf-8")
    assert migrate(str(tmp_path / "absent" / "p.json"), str(tmp_path)) == []
    assert (tmp_path / "quota.txt").exists()            # rien perdu
