"""« iris aide » (toutes les commandes, celles du mode en tête) et « iris guide » (documentation)."""
from motionzero.aide import help_view, said_words
from motionzero.calendar_view import WORDS as CAL
from motionzero.config import Config
from motionzero.core import ALIASES, CHROME_KEYS, Core, Mode
from motionzero.fenetre import GUIDE_URL, window_actions
from motionzero.voice import WORDS


def test_chaque_mot_ecoute_est_dans_l_aide():
    """L'ancienne aide listait 20 mots sur 65 : celle-ci doit tous les citer (sauf calendrier et synonymes)."""
    rest = {"iris", "space", "agrandis", "wake"}   # « space » = espace ; agrandis / wake cités dans les effets
    missing = [w for w in WORDS if w not in said_words() | set(ALIASES) | set(CAL) | rest]
    assert missing == []


def test_aide_ouverte_puis_fermee():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("aide", 1.5)
    assert core.help_until > 2.0
    assert core.voice("merci", 3.0) == []            # « merci » ferme sans « iris »
    assert core.help_until < 3.0


def test_aide_redite_la_ferme_et_ferme_aussi():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("aide", 1.2)
    core.voice("iris", 2.0)
    core.voice("aide", 2.2)
    assert core.help_until < 2.2
    core.voice("iris", 3.0)
    core.voice("aide", 3.2)
    core.voice("ferme", 4.0)
    assert core.help_until < 4.0


def test_aide_fermee_seule_et_par_stop():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("aide", 1.2)
    core.voice("stop", 2.0)
    assert core.help_until < 2.0
    core.voice("iris", 3.0)
    core.voice("aide", 3.2)
    from motionzero.core import HELP_S
    assert core.help_until == 3.2 + HELP_S              # sans rien dire : fermée seule


def test_ferme_sans_aide_garde_son_sens():
    """Aide fermée : « ferme » seul ne fait rien de neuf (pas de régression)."""
    core = Core(Config())
    assert core.voice("ferme", 1.0) == []


def test_bloc_maintenant_selon_le_mode():
    assert help_view(Mode.NEUTRAL)["now"]["title"] == "Maintenant"
    chrome = help_view(Mode.CHROME)["now"]["rows"]
    assert [w for w, _ in chrome] == list(CHROME_KEYS)
    assert help_view(Mode.DISABLED)["now"]["rows"][0][0] == "iris reprise"
    assert "Calendrier" in help_view(Mode.NEUTRAL, calendar_open=True)["now"]["title"]
    assert [w for w, _ in help_view(Mode.NEUTRAL, confirming=True)["now"]["rows"]] == ["envoie", "annule"]


def test_guide_ouvre_la_doc_sur_github():
    core = Core(Config())
    core.voice("iris", 1.0)
    acts = core.voice("guide", 1.5)
    assert ("guide",) in acts
    opened = []
    rest = window_actions(acts + [("autre",)], opener=opened.append)
    assert opened == [GUIDE_URL] and ("autre",) in rest and ("guide",) not in rest
    assert GUIDE_URL.startswith("https://github.com/") and GUIDE_URL.endswith("docs/guide/README.md")


def test_guide_echec_d_ouverture_ne_plante_pas(monkeypatch):
    import os
    from motionzero import fenetre

    def boom(url):
        raise OSError("pas de navigateur")
    monkeypatch.setattr(os, "startfile", boom, raising=False)
    assert fenetre.open_url(GUIDE_URL) is False
