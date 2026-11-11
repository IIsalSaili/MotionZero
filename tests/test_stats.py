"""Panneau de consommation : mesures réelles, pannes, et aucune mesure quand la page est réduite."""
import threading

from motionzero import stats


def test_mesure_reelle_contient_l_essentiel():
    s = stats.Stats(lambda: {"whisper": False, "detect_hz": 5})
    r = s.sample()
    for k in ("app_cpu", "app_cpu_core", "app_private", "cores", "pc_cpu", "pc_ram_total", "threads"):
        assert k in r, k
    assert len(r["cores"]) == r["ncpu"]
    assert r["detect_hz"] == 5 and r["whisper"] is False
    assert any(label == "interface" for label, _ in r["threads"])   # le fil qui mesure ici


def test_carte_graphique_absente_affichee_indisponible(monkeypatch):
    import pynvml

    def boom():
        raise pynvml.NVMLError(1)
    monkeypatch.setattr(pynvml, "nvmlInit", boom)
    monkeypatch.setattr(stats, "_GpuProcess", lambda pid: (_ for _ in ()).throw(OSError("pdh")))
    r = stats.Stats().sample()
    assert r.get("pc_vram_total") is None and r.get("app_vram") is None and r["gpu_name"] is None
    assert "app_cpu" in r                     # le reste est toujours mesuré


def test_etat_des_modeles_en_panne_ne_casse_pas_la_mesure():
    r = stats.Stats(lambda: 1 / 0).sample()
    assert "pc_cpu" in r


def test_historique_limite_a_60_s():
    s = stats.Stats()
    for _ in range(70):
        s.sample()
    assert len(s.history["pc_cpu"]) == stats.HISTORY


def test_page_reduite_aucune_mesure(monkeypatch):
    created, emitted = [], []
    monkeypatch.setattr(stats, "Stats", lambda info: created.append(1))
    stop = threading.Event()
    n = {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] >= 5:
            stop.set()
    monkeypatch.setattr(stats.time, "sleep", sleep)
    stats.run_sampler(lambda: False, emitted.append, stop=stop)
    assert created == [] and emitted == []


def test_mesure_en_panne_le_fil_continue(monkeypatch):
    class Bad:
        def __init__(self, info):
            pass

        def sample(self):
            raise RuntimeError("psutil en panne")
    monkeypatch.setattr(stats, "Stats", Bad)
    stop, n = threading.Event(), {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] >= 6:
            stop.set()
    monkeypatch.setattr(stats.time, "sleep", sleep)
    stats.run_sampler(lambda: True, lambda s: None, stop=stop)   # ne lève pas
    assert n["i"] >= 6


def test_panneau_se_dessine_avec_et_sans_mesures():
    from motionzero.ui import ConsoPanel, QApplication
    QApplication.instance() or QApplication([])
    w = ConsoPanel()
    w.resize(340, 640)
    w.grab()                                   # « mesure en cours… »
    w.set_stats(stats.Stats(lambda: {"whisper": True, "detect_hz": 20, "voice_on": True}).sample())
    w.grab()
    w.set_stats({"ncpu": 12})                  # mesure presque vide : pas de plantage
    w.grab()
