"""Voix basse (13/11) : le soir, parlé doucement, les mots étaient « ignorés : pas sûr de l'avoir entendu »."""
import queue
from types import SimpleNamespace

from motionzero.app import Engine, next_quiet, read_quiet
from motionzero.voice import confirmed, quiet_active


def w(*names, conf=1.0):
    return [{"word": n, "conf": conf} for n in names]


def test_actif_le_soir_en_auto():
    assert quiet_active("auto", 22) and quiet_active("auto", 23) and quiet_active("auto", 3)
    assert not quiet_active("auto", 7) and not quiet_active("auto", 21)
    assert quiet_active("oui", 12) and not quiet_active("non", 23)


def test_mot_seul_murmure_accepte_en_voix_basse():
    """Mesuré : « skip » dit bas, la reconnaissance libre n'entend rien (texte vide)."""
    assert not confirmed(w("skip"), "")
    assert confirmed(w("skip"), "", quiet=True)


def test_iris_deforme_accepte_en_voix_basse():
    """Mesuré : « iris claude » entendu librement « cerise claude »."""
    got = w("iris", "claude", conf=0.8)
    assert not confirmed(got, "cerise claude", n_heard=4)
    assert confirmed(got, "cerise claude", n_heard=4, quiet=True)
    assert confirmed(got, "", n_heard=2, quiet=True)            # « iris » à 0,8, phrase courte


def test_conversation_toujours_refusee_en_voix_basse():
    assert not confirmed(w("envoie"), "tu as vu la série hier soir", quiet=True)
    assert not confirmed(w("iris", "colle", conf=0.5), "il colle sur la table", n_heard=5, quiet=True)


def test_choix_de_l_accueil(tmp_path):
    assert [next_quiet("auto"), next_quiet("oui"), next_quiet("non"), next_quiet("??")] == ["oui", "non", "auto", "auto"]
    assert read_quiet(str(tmp_path / "absent.txt")) == "auto"         # fichier absent
    bad = tmp_path / "v.txt"
    bad.write_text("n'importe quoi", encoding="utf-8")
    assert read_quiet(str(bad)) == "auto"                              # contenu illisible


def test_bouton_previent_le_micro(tmp_path, monkeypatch):
    import motionzero.app as app
    monkeypatch.setattr(app, "QUIET_FILE", str(tmp_path / "v.txt"))
    emitted = []
    d = SimpleNamespace(quiet_requests=queue.Queue(), quiet_choice="non",
                        listener=SimpleNamespace(quiet=False),
                        bridge=SimpleNamespace(quiet=SimpleNamespace(emit=emitted.append)))
    eng = Engine.__new__(Engine)
    eng.d, eng.quiet_check_t, eng.quiet_choice = d, -1e9, "non"
    eng._quiet(1.0)
    assert d.listener.quiet is False
    d.quiet_requests.put(1)                     # « jamais » -> « le soir »
    d.quiet_requests.put(1)                     # -> « toujours »
    eng._quiet(1.1)
    assert eng.quiet_choice == "oui" and emitted == ["auto", "oui"] and d.listener.quiet is True
    assert read_quiet(app.QUIET_FILE) == "oui"


def test_sans_micro_rien_ne_plante():
    d = SimpleNamespace(quiet_requests=queue.Queue(), listener=None)
    eng = Engine.__new__(Engine)
    eng.d, eng.quiet_check_t, eng.quiet_choice = d, -1e9, "auto"
    eng._quiet(1.0)
