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


def test_focus_s_eteint_seul_et_jamais_en_pause():
    c = Core(Config())
    _say(c, 0.0, "iris", "focus")
    c.voice("quota", 100.0)                                         # une commande prolonge
    assert c.focus_on(100.0 + FOCUS_IDLE_S - 1)
    assert not c.focus_on(100.0 + FOCUS_IDLE_S + 1)                 # 10 min sans commande : éteint
    c2 = Core(Config())
    _say(c2, 0.0, "iris", "focus")
    c2.set_mode(Mode.DISABLED, 1.0, [])
    assert not c2.focus_on(2.0)


def test_souris_bouton_tenu_clic_et_scroll_sans_iris():
    c = Core(Config())
    c.dragging = True                                               # « iris glisse » : bouton tenu, souris éteinte
    assert ("click", "left") in c.voice("clic", 5.0, t_start=4.8)
    c2 = Core(Config())
    c2.set_mouse(True, 1.0, [])
    c2.voice("scroll", 5.0, t_start=4.8)
    assert c2.last_word[:3:2] == ("scroll", True)
    c3 = Core(Config())                                             # souris éteinte : scroll seul ignoré
    c3.voice("scroll", 5.0)
    assert not c3.last_word[2]


def test_hold_enfonce_puis_relache():
    from motionzero.voice import WORDS
    from motionzero.core import ALIASES
    assert ALIASES["old"] == ALIASES["hole"] == "hold" and "hold" in WORDS
    assert "glisse" not in WORDS and "lâche" not in WORDS
    c = Core(Config())
    c.set_mouse(True, 1.0, [])
    acts = c.voice("hold", 5.0, t_start=4.8)                        # souris : sans « iris »
    assert c.dragging and any(a[0] == "press" for a in acts)
    acts = c.voice("hold", 8.0, t_start=7.8)                        # redit : relâché
    assert not c.dragging and ("release", "mouse", "left") in acts
    c2 = Core(Config())                                             # souris éteinte, sans « iris » : rien
    assert c2.voice("hold", 5.0) == [] and not c2.dragging
