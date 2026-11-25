"""Refonte de l'accueil (plan-accueil.md) : registre des réglages, lecture à voix haute, sections."""
import queue
from types import SimpleNamespace

import pytest

from motionzero import reglages
from motionzero.reglages import GROUPES, IDS, REGLAGES, par_groupe, read_flag, read_section, tile_text, write_flag, \
    write_section

VALEURS = {"souris": ("main", "tete"), "camera": (False, True), "conversation": (True, False),
           "voix_basse": ("auto", "oui", "non"), "volume": (0.3, 0.5, 0.7, 1.0), "lecture": (False, True),
           "son": (False, True)}


def test_registre_complet():
    assert len(set(IDS)) == len(IDS)
    for r in REGLAGES:
        assert r.titre and r.groupe in GROUPES
        assert r.id in VALEURS                  # chaque réglage a ses valeurs testées ici
        for v in VALEURS[r.id]:
            text, note, tone = tile_text(r.id, v)
            assert text != "?" and tone in ("ok", "alerte", "neutre")
    assert [g for g, _ in par_groupe()] == [g for g in GROUPES if any(r.groupe == g for r in REGLAGES)]


def test_valeurs_inattendues_sans_plantage():
    assert tile_text("inconnu", 1)[0] == "?"
    assert tile_text("volume", None)[0] == "?"
    assert tile_text("voix_basse", "nimporte")[0] == "Le soir"


def test_lecture_decochee_par_defaut(tmp_path):
    p = tmp_path / "lecture.txt"
    assert read_flag(str(p)) is False           # absent
    p.write_text("n'importe quoi", encoding="utf-8")
    assert read_flag(str(p)) is False           # illisible
    write_flag(str(p), True)
    assert read_flag(str(p)) is True
    write_flag(str(tmp_path / "absent" / "x.txt"), True)   # dossier absent : avertissement, pas d'exception


def test_section_gardee(tmp_path):
    p = str(tmp_path / "s.txt")
    assert read_section(p) == "maintenant"
    write_section("conso", p)
    assert read_section(p) == "conso"
    write_section("bidon", p)
    assert read_section(p) == "maintenant"


def test_voix_coupee_ne_lit_rien_meme_force():
    from motionzero.speech import Speaker
    said = []

    class Voice:
        def Speak(self, text, flags=0):
            said.append(text)

        def WaitUntilDone(self, ms):
            return True
    s = Speaker(factory=lambda rate: Voice())
    s.allowed = False
    assert s.say("rappel", force=True) is False and s.say("message") is False
    s.allowed = True
    assert s.say("rappel", force=True) is True


def _engine(tmp_path, monkeypatch, speaker):
    from motionzero.app_ecoute import EcouteMixin
    monkeypatch.setattr(reglages, "LECTURE_FILE", str(tmp_path / "lecture.txt"))
    shown = []
    d = SimpleNamespace(lecture_requests=queue.Queue(), lecture=False, speaker=speaker,
                        bridge=SimpleNamespace(lecture=SimpleNamespace(emit=shown.append)))
    eng = EcouteMixin()
    eng.d = d
    return eng, d, shown


def test_case_lecture_bascule_et_enregistre(tmp_path, monkeypatch):
    sp = SimpleNamespace(allowed=False, hushed=0)
    sp.hush = lambda: setattr(sp, "hushed", sp.hushed + 1)
    eng, d, shown = _engine(tmp_path, monkeypatch, sp)
    d.lecture_requests.put(1)
    eng._lecture()
    assert d.lecture and sp.allowed and shown == [True] and read_flag(reglages.LECTURE_FILE) is True
    d.lecture_requests.put(1)
    eng._lecture()
    assert not d.lecture and not sp.allowed and sp.hushed == 1 and shown == [True, False]


def test_case_lecture_sans_voix(tmp_path, monkeypatch):
    eng, d, shown = _engine(tmp_path, monkeypatch, None)
    d.lecture_requests.put(1)
    eng._lecture()                              # voix Windows absente : enregistré quand même, pas d'exception
    assert d.lecture and shown == [True]


@pytest.fixture
def qt():
    from motionzero.ui import QApplication
    return QApplication.instance() or QApplication([])


def test_textes_des_cartes_tiennent(qt):
    from motionzero.ui_accueil_pages import TILE_W, fits
    for r in REGLAGES:
        assert fits(r.titre.upper(), 15, TILE_W - 36), r.titre
        for v in VALEURS[r.id]:
            text, note, _ = tile_text(r.id, v)
            assert fits(text, 24, TILE_W - 36), text
            assert fits(note, 15, TILE_W - 36, bold=False), note


def test_page_trois_sections_et_etats(qt, tmp_path):
    import numpy as np
    from motionzero.ui import PreviewWindow
    f = str(tmp_path / "sec.txt")
    w = PreviewWindow(section_file=f)
    assert w.section == "maintenant"
    for name in ("reglages", "conso", "maintenant"):
        w.nav[name].click()
        assert w.section == name
        w.grab()
    w.nav["conso"].click()
    assert read_section(f) == "conso"
    assert PreviewWindow(section_file=f).section == "conso"   # gardée d'un démarrage à l'autre
    w.set_camera(True)                          # caméra coupée
    w.set_stats(None)                           # mesures absentes
    w.set_stats({"app_cpu": 5, "history": {"app_cpu": [1, 5, 3], "pc_cpu": [20, None, 30]},
                 "threads": [("voix", 12.0), ("bizarre",)], "whisper": True, "detect_hz": 15})
    w.set_frame(np.zeros((480, 640, 3), np.uint8))   # section cachée : ignorée sans erreur
    w.set_lecture(True)
    w.set_repair_busy(True)
    assert w.settings.tiles["lecture"].v.text() == "Activée"
    w.grab()


def test_details_de_conso():
    from motionzero.ui_accueil_pages import conso_details
    assert conso_details(None) == ["Mesure en cours…"]
    lines = conso_details({"app_cpu": 6, "pc_cpu": 30, "app_private": 1434, "pc_ram_used": 9.2, "pc_ram_total": 16,
                           "app_gpu": 12, "whisper": False, "detect_hz": 15, "threads": [("voix", 3.0)]})
    assert lines[0] == "Processeur : Iris 6 % · PC 30 %" and "1,4 Go" in lines[1]
    assert any("Whisper au repos" in l for l in lines) and any("voix 3 %" in l for l in lines)
