"""Mode focus (« iris focus ») et mots de la souris sans « iris » (15/11)."""
from motionzero.config import Config
from motionzero.core import Core, Mode, FOCUS_IDLE_S
from motionzero.voice import WORDS


def _say(c, t, *words):
    out = []
    for i, w in enumerate(words):
        out += c.voice(w, t + i * 0.3, t_start=t + i * 0.3 - 0.2)
    return out


def test_focus_commandes_sans_iris_puis_eteint():
    assert "focus" in WORDS
    c = Core(Config())
    assert _say(c, 10.0, "chrome") == [] and not c.last_word[2]     # sans focus : ignoré
    _say(c, 20.0, "iris", "focus")
    assert c.focus_on(21.0)
    assert c.voice("chrome", 22.0) and c.last_word[2]               # accepté sans « iris »
    _say(c, 30.0, "focus")                                          # « focus » seul : éteint
    assert not c.focus_on(31.0)
    assert c.voice("chrome", 32.0) == [] and not c.last_word[2]


def test_focus_ne_s_eteint_jamais_seul_ni_en_pause():
    c = Core(Config())
    _say(c, 0.0, "iris", "focus")
    assert c.focus_on(24 * 3600.0)                                  # 19/11 : plus de minuteur
    c2 = Core(Config())
    _say(c2, 0.0, "iris", "focus")
    c2.set_mode(Mode.DISABLED, 1.0, [])
    assert not c2.focus_on(2.0)


def test_souris_bouton_tenu_clic_et_scroll_sans_iris():
    c = Core(Config())
    c.dragging = True                                               # « iris agrippe » : bouton tenu, souris éteinte
    assert ("click", "left") in c.voice("clic", 5.0, t_start=4.8)
    c2 = Core(Config())
    c2.set_mouse(True, 1.0, [])
    c2.voice("scroll", 5.0, t_start=4.8)
    assert c2.last_word[:3:2] == ("scroll", True)
    c3 = Core(Config())                                             # souris éteinte : scroll seul ignoré
    c3.voice("scroll", 5.0)
    assert not c3.last_word[2]


def test_agrippe_enfonce_puis_relache():
    assert "agrippe" in WORDS and "glisse" not in WORDS and "lâche" not in WORDS
    c = Core(Config())
    c.set_mouse(True, 1.0, [])
    acts = c.voice("agrippe", 5.0, t_start=4.8)                     # souris : sans « iris »
    assert c.dragging and ("press", "mouse", "left", "sticky") in acts
    acts = c.voice("agrippe", 8.0, t_start=7.8)                     # redit : relâché
    assert not c.dragging and ("release", "mouse", "left") in acts
    c2 = Core(Config())                                             # souris éteinte, sans « iris » : rien
    assert c2.voice("agrippe", 5.0) == [] and not c2.dragging


def test_clic_ecoute_souris_eteinte():
    """16/11 : souris éteinte, « clic » absent de la liste écoutée : « iris clic » devenait « iris lis »."""
    import json
    from motionzero.voice import GRAMMARS
    base = json.loads(GRAMMARS["base"])
    assert "iris clic" in base and "iris double clic" in base and "clic" not in base
    c = Core(Config())
    assert ("click", "left") in _say(c, 10.0, "iris", "clic")        # souris éteinte : « iris clic »
    _say(c, 20.0, "iris", "focus")
    assert ("click", "left") in c.voice("clic", 22.0, t_start=21.8)  # focus : « clic » seul


def test_clic_seul_ignore_sans_focus_ni_souris():
    c = Core(Config())
    assert c.voice("clic", 5.0, t_start=4.8) == []
