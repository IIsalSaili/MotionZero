"""Raccourcis Discord lus depuis ses réglages (entrée « keybinds »)."""
import json

from motionzero.discord_keys import parse_keybinds


def _raw(state):
    return b"\x01" + json.dumps({"_state": state, "_version": 2}).encode("latin-1")


def test_lit_le_raccourci_de_mute():
    raw = _raw({"17": {"action": "TOGGLE_MUTE", "shortcut": [[0, 110, "0:0"], [0, 107, "0:0"]], "enabled": True},
                "13": {"action": "SAVE_SCREENSHOT", "shortcut": [[0, 123, 1]], "enabled": True}})
    binds = parse_keybinds(raw)
    assert binds["TOGGLE_MUTE"] == [110, 107] and binds["SAVE_SCREENSHOT"] == [123]


def test_ignore_desactives_vides_et_souris():
    raw = _raw({"1": {"action": "TOGGLE_DEAFEN", "shortcut": [[0, 120, 1]], "enabled": False},
                "2": {"action": "PUSH_TO_TALK", "shortcut": [], "enabled": True},
                "3": {"action": "TOGGLE_MUTE", "shortcut": [[1, 4, 1]], "enabled": True}})
    assert parse_keybinds(raw) == {}


def test_base_absente():
    assert parse_keybinds(None) == {}


def test_etat_micro_et_sourdine():
    from motionzero.discord_keys import parse_voice_state
    raw = b"\x01" + json.dumps({"default": {"mute": True, "deaf": False}, "stream": {"mute": False}}).encode()
    assert parse_voice_state(raw) == (True, False)
    assert parse_voice_state(None) is None


def test_icones_discord():
    from motionzero.ui import discord_icons
    assert discord_icons(None) == [] and discord_icons((False, False)) == []
    assert discord_icons((True, False)) == ["mic-off"]
    assert discord_icons((True, True)) == ["headphone-off", "mic-off"]
    assert discord_icons((False, True)) == ["headphone-off", "mic-off"]


def test_mute_selon_l_etat_reel():
    from motionzero.discord_keys import mute_needed
    assert mute_needed(True, (False, False))          # allumé + « mute » : on coupe
    assert not mute_needed(True, (True, False))       # déjà coupé : rien (sinon ça rallumerait)
    assert mute_needed(False, (True, False))          # coupé + « démute » : on rallume
    assert not mute_needed(False, (False, False))     # déjà allumé : rien
    assert mute_needed(True, None) and mute_needed(False, None)   # état illisible : on envoie
