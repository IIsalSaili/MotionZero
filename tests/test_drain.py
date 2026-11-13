"""Files vidées par la boucle principale : chaque élément pris une fois, jamais de boucle infinie."""
import queue

from motionzero.app import drain


def test_drain_vide_la_file():
    q = queue.Queue()
    q.put(1)
    q.put(2)
    assert drain(q) == [1, 2]
    assert q.empty() and drain(q) == []


def test_bouton_main_tete_bascule_une_seule_fois():
    from motionzero.config import Config
    from motionzero.core import Core
    core, q = Core(Config()), queue.Queue()
    avant = core.pointer
    q.put(1)                                   # un clic sur le bouton de l'accueil
    for _ in drain(q):
        core.set_pointer_toggle(0.0)
    assert core.pointer != avant and q.empty()
