"""État de Discord suivi par motionzero : jamais d'inversion par une commande répétée, survit aux redémarrages."""
import os
import tempfile

from motionzero import vscode


def _setup(monkeypatch, sent):
    monkeypatch.setattr(vscode, "discord_mute_toggle", lambda: sent.append(1) or True)
    vscode.STATE_PATH = os.path.join(tempfile.mkdtemp(), "discord_state.json")
    vscode.discord_muted = False


def test_mute_repete_ne_rallume_pas(monkeypatch):
    """Mesuré le 10/11 : deux « mute » de suite rallumaient le micro."""
    sent = []
    _setup(monkeypatch, sent)
    vscode.discord_mute()
    vscode.discord_mute()
    assert sent == [1] and vscode.discord_muted
    vscode.discord_unmute()
    vscode.discord_unmute()
    assert sent == [1, 1] and not vscode.discord_muted


def test_etat_survit_au_redemarrage(monkeypatch):
    sent = []
    _setup(monkeypatch, sent)
    vscode.discord_mute()
    vscode.discord_muted = False           # redémarrage : mémoire perdue…
    vscode.load_discord_state()            # … mais relue depuis le fichier
    assert vscode.discord_muted
    vscode.discord_unmute()
    assert sent == [1, 1] and not vscode.discord_muted
