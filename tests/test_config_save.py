"""Écriture sûre de config.json : un fichier coupé ne fait pas perdre les réglages."""
import json
import os

from motionzero.config import Config, load_config, save_config


def test_save_puis_load(tmp_path):
    p = str(tmp_path / "config.json")
    cfg = Config()
    save_config(cfg, p)
    assert not os.path.exists(p + ".tmp")
    assert load_config(p) == cfg


def test_fichier_coupe_reprend_la_sauvegarde(tmp_path):
    p = str(tmp_path / "config.json")
    a = Config()
    save_config(a, p)
    b = Config()
    first = next(f for f in vars(b) if isinstance(getattr(b, f), (int, float)) and not isinstance(getattr(b, f), bool))
    setattr(b, first, getattr(b, first) + 1)
    save_config(b, p)                       # a est maintenant en .bak
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"coupe": ')              # plantage pendant une écriture à la main
    assert load_config(p) == a


def test_fichier_et_sauvegarde_illisibles(tmp_path):
    p = str(tmp_path / "config.json")
    for name in (p, p + ".bak"):
        with open(name, "w", encoding="utf-8") as fh:
            fh.write("pas du json")
    assert load_config(p) == Config()


def test_json_qui_nest_pas_un_objet(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump([1, 2], fh)
    assert load_config(p) == Config()


def test_fichier_absent(tmp_path):
    assert load_config(str(tmp_path / "rien.json")) == Config()
