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
