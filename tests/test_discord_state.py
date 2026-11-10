"""État de Discord suivi par motionzero : survit aux redémarrages ; « mute / démute » dits exprès forcent."""
import os
import tempfile

from motionzero import vscode


def _setup(monkeypatch, sent):
    monkeypatch.setattr(vscode, "discord_mute_toggle", lambda: sent.append(1) or True)
    vscode.STATE_PATH = os.path.join(tempfile.mkdtemp(), "discord_state.json")
    vscode.discord_muted = False


def test_etat_survit_au_redemarrage(monkeypatch):
    sent = []
    _setup(monkeypatch, sent)
    vscode.discord_mute()                  # « iris claude » : coupé
    vscode.discord_muted = False           # redémarrage : mémoire perdue…
    vscode.load_discord_state()            # … mais relue depuis le fichier
    assert vscode.discord_muted
    vscode.discord_unmute()                # « iris retour » : rallume bien
    assert len(sent) == 2 and not vscode.discord_muted


def test_demute_dit_expres_envoie_toujours(monkeypatch):
    sent = []
    _setup(monkeypatch, sent)
    vscode.discord_unmute()                # automatique, rien de coupé par nous : rien
    assert sent == []
    vscode.discord_unmute(force=True)      # « iris démute » : on envoie quand même
    assert sent == [1]
