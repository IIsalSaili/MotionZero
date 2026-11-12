"""Lecteur de sons : mélange, alarme progressive en boucle, arrêt, pannes. Sans carte son."""
import os

import numpy as np

from motionzero.sounds import RATE, Mixer, Sounds, is_failure, ramp_gain

ROOT = os.path.join(os.path.dirname(__file__), "..", "assets", "sounds")


def test_son_fini_retire():
    m = Mixer()
    m.add(np.full(100, 0.2, np.float32))
    out = m.fill(150)
    assert abs(out[0] - 0.2) < 1e-6 and out[120] == 0
    assert m.fill(10).max() == 0 and m.voices == []


def test_alarme_part_tout_bas_puis_monte():
    assert ramp_gain(0) < 0.011 and ramp_gain(30) < ramp_gain(60) and ramp_gain(120) == ramp_gain(60)
    m = Mixer()
    m.start_alarm(np.ones(RATE, np.float32))
    debut = m.fill(RATE).max()
    for _ in range(59):
        m.fill(RATE)                                     # la boucle continue au-delà de la durée du fichier
    fin = m.fill(RATE).max()
    assert debut < 0.02 and fin > 0.5 and m.ringing


def test_rejouer_l_alarme_ne_la_relance_pas():
    m = Mixer()
    m.start_alarm(np.ones(RATE, np.float32))
    m.fill(RATE * 10)
    m.start_alarm(np.ones(RATE, np.float32))             # Desk rejoue « ALARME » toutes les 1,5 s
    assert m.alarm_t == RATE * 10


def test_stop_coupe_vite_sans_clic():
    m = Mixer()
    m.start_alarm(np.ones(RATE, np.float32))
    m.fill(RATE * 61)
    m.stop_alarm()
    bloc = m.fill(4410)                                  # 100 ms
    assert bloc[0] > 0.3 and bloc[-1] == 0 and not m.ringing


def test_carte_son_en_panne_iris_continue():
    def boom(mixer):
        raise OSError("aucune sortie audio")
    s = Sounds(ROOT, stream_factory=boom)
    s.play("ECOUTE")
    s.play("ALARME")                                     # aucune exception
    assert s.stream is None and not s.ringing


class FakeStream:
    def __init__(self, mixer):
        self.mixer = mixer


def test_sons_choisis_charges_et_clic_muet():
    s = Sounds(ROOT, stream_factory=FakeStream)
    assert set(s.data) == {"ECOUTE", "OK", "NON", "MODE", "PARLE", "COUPE", "RAPPEL", "ALARME"}
    s.play("CLIC")
    assert s.mixer.voices == []                          # le clic n'a plus de son
    s.play("CHROME")
    s.play("SOURIS")
    assert len(s.mixer.voices) == 2                      # les modes partagent le son MODE


def test_fichier_absent_ne_plante_pas(tmp_path):
    s = Sounds(str(tmp_path), stream_factory=FakeStream)
    s.play("OK")
    assert s.data == {} and s.mixer.voices == []


def test_sons_coupes_dans_la_config():
    s = Sounds(ROOT, enabled=False, stream_factory=FakeStream)
    s.play("OK")
    assert s.stream is None


def test_echecs_reconnus():
    for label in ("RIEN ENTENDU : timer annule", "VOLUME : pas compris « x »", "VOLUME : reglage impossible",
                  "CHROME PAS DEVANT : rien envoye", "BOT DISCORD ABSENT"):
        assert is_failure(label), label
    for label in ("ONGLET SUIVANT", "VOLUME 40 %", '"clic" ignore : dis IRIS avant', None, ""):
        assert not is_failure(label), label


def test_un_seul_son_a_la_fois():
    """« iris stop » dit d'un trait : le son d'« iris » et celui du mode ne s'additionnent plus."""
    m = Mixer()
    m.add(np.full(RATE, 0.6, np.float32))
    m.add(np.full(RATE, 0.6, np.float32))
    out = m.fill(4000)
    assert abs(out[2000] - 0.6) < 1e-6              # après 20 ms : un seul son (pas 1,2)
    assert len(m.voices) == 1


def test_l_alarme_continue_quand_un_son_arrive():
    m = Mixer()
    m.start_alarm(np.ones(RATE, np.float32))
    m.add(np.full(100, 0.1, np.float32))
    m.fill(RATE)
    assert m.ringing


def test_volume_general():
    m = Mixer()
    m.volume = 0.5
    m.add(np.full(10, 0.8, np.float32))
    assert abs(m.fill(10)[0] - 0.4) < 1e-6
    from motionzero.config import Config
    assert Config().sound_volume == 0.5
