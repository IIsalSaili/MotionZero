"""Pont VS Code : onglet suivant / précédent par l'extension, effet vérifié ; secours par touche sinon."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import motionzero.app as app
import motionzero.pont as pont
import motionzero.vscode as vs
from motionzero.config import Config
from motionzero.core import Core
from motionzero.sounds import is_failure

PREV = [("editor_tab", ["ctrl", "pageup"])]
NEXT = [("editor_tab", ["ctrl", "pagedown"])]


def test_pont_ok_pas_de_touche(monkeypatch):
    vus = []
    monkeypatch.setattr(pont, "command", lambda n: vus.append(n) or (True, "core.py"))
    core = Core(Config())
    assert app.vscode_actions(PREV, core, None, None, 1.0) == []      # aucune touche simulée
    assert vus == ["prev"]
    assert "PRECEDENT" in core.last_gesture[0] and not is_failure(core.last_gesture[0])
    app.vscode_actions(NEXT, core, None, None, 2.0)
    assert vus[-1] == "next"


def test_pont_onglet_inchange_annonce_echec(monkeypatch):
    monkeypatch.setattr(pont, "command", lambda n: (False, "onglet inchange"))
    core = Core(Config())
    assert app.vscode_actions(PREV, core, None, None, 1.0) == []
    assert is_failure(core.last_gesture[0])        # jamais « fait » quand rien n'a bougé


def test_pont_absent_secours_touche(monkeypatch):
    monkeypatch.setattr(vs, "vscode_in_front", lambda: True)
    core = Core(Config())
    assert app.vscode_actions(NEXT, core, None, None, 1.0) == [("hotkey", ["ctrl", "pagedown"])]


@pytest.fixture
def faux_vscode(monkeypatch):
    """Vrai serveur HTTP local qui répond comme l'extension."""
    rep = {"body": b'{"ok": true, "label": "app.py"}'}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            rep["path"] = self.path
            self.send_response(200)
            self.end_headers()
            self.wfile.write(rep["body"])

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.undo()                              # le vrai pont.command (conftest le coupe)
    monkeypatch.setattr(pont, "PORT", srv.server_address[1])
    yield rep
    srv.shutdown()


def test_client_reponses(faux_vscode):
    assert pont.command("prev") == (True, "app.py") and faux_vscode["path"] == "/prev"
    faux_vscode["body"] = json.dumps({"ok": False, "reason": "un seul onglet"}).encode()
    assert pont.command("next") == (False, "un seul onglet")
    faux_vscode["body"] = b"pas du json"
    assert pont.command("next") is None             # réponse illisible : secours


def test_client_injoignable(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(pont, "PORT", 1)            # personne n'écoute
    assert pont.command("next") is None
