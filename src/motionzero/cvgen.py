"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN.

Iris appelle les adresses que les boutons de CVGEN appellent déjà : pour CVGEN, c'est comme un clic. Toutes ces
adresses sont ici (ROUTES), et un test vérifie qu'elles existent encore dans server.mjs.

Les appels HTTP tournent dans le fil « cvgen » ; ils ne rendent compte que par la queue `_q`, lue par events()
dans la boucle principale (jamais Core ailleurs).
"""
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("motionzero.cvgen")

BASE = "http://127.0.0.1:3000"
DIR = Path.home() / "Desktop" / "CVGEN"
TIMEOUT_S = 8
START_WAIT_S = 20.0      # CVGEN lancé par Iris : temps laissé pour qu'il réponde
SHOW_S = 15.0            # la carte reste ce temps
CLOSE_HINT = "« candidature » pour quitter"

# Adresses de CVGEN utilisées par Iris (mêmes que celles des boutons). Vérifiées par tests/test_cvgen.py.
ROUTES = {
    "sante": ("GET", "/api/health"),
    "agent": ("GET", "/api/agent"),
    "demarrer": ("POST", "/api/agent/demarrer"),
    "arreter": ("POST", "/api/agent/arreter"),
    "compte": ("GET", "/api/offres/compte"),
    "preparation": ("GET", "/api/preparation"),
}

# Mots du mode (sans « iris » tant qu'il est allumé). Tous présents dans le modèle Vosk (vérifié le 17/11).
WORDS = {"cherche": "lance ou arrête la recherche",
         "état": "où en est CVGEN",
         "offres": "la page des offres"}

ETATS = (("verif", "à vérifier"), ("tri", "à trier"), ("ok", "postulées"), ("ref", "refusées"))


class CvgenError(Exception):
    """Message court, affichable tel quel."""


def _http(method, path, base=BASE, timeout=TIMEOUT_S):
    req = urllib.request.Request(base + path, method=method, data=b"{}" if method != "GET" else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except (ValueError, OSError):
            msg = None
        raise CvgenError(msg or f"CVGEN a refusé ({e.code})") from None
    except (OSError, ValueError):
        raise CvgenError("CVGEN ne répond pas") from None


def _launch(root=DIR):
    """Démarre `node server.mjs` sans fenêtre, détaché d'Iris (il survit à une relance d'Iris)."""
    node = shutil.which("node")
    if node is None or not (Path(root) / "server.mjs").exists():
        raise CvgenError("CVGEN introuvable sur ce PC")
    flags = 0x08000000 | 0x00000200   # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([node, "server.mjs"], cwd=str(root), creationflags=flags if os.name == "nt" else 0,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call(name, http=_http):
    method, path = ROUTES[name]
    return http(method, path)


def summary(agent, compte, prep):
    """Lignes de la carte « état ». Pur : testable."""
    etat = (agent or {}).get("etat")
    lines = ["Recherche en cours" if etat == "en-cours" else
             "Recherche en train de s'arrêter" if etat == "arret-demande" else "Recherche arrêtée"]
    counts = [f"{(compte or {}).get(k, 0)} {lbl}" for k, lbl in ETATS if (compte or {}).get(k)]
    lines.append(" · ".join(counts) if counts else "Aucune offre en attente")
    if (prep or {}).get("offreId"):
        lines.append("Une candidature est en préparation")
    msg = (agent or {}).get("message")
    if msg:
        lines.append(str(msg)[:80])
    return lines


class Candidature:
    def __init__(self, http=_http, launch=_launch, open_url=None, clock=time.monotonic, sleep=time.sleep):
        self.http, self.launch, self.open_url = http, launch, open_url
        self.clock, self.sleep = clock, sleep
        self._q = queue.Queue()
        self.busy = False
        self.title = self.lines = self.meta = None
        self.show_until = -1e9

    # ---- fil « cvgen » ----
    def _ensure(self):
        """CVGEN joignable, lancé au besoin. Lève CvgenError sinon."""
        try:
            return call("sante", self.http)
        except CvgenError:
            pass
        self._q.put(("wait", "CVGEN démarre…"))
        self.launch()
        end = self.clock() + START_WAIT_S
        while self.clock() < end:
            self.sleep(1.0)
            try:
                return call("sante", self.http)
            except CvgenError:
                continue
        raise CvgenError("CVGEN n'a pas démarré")

    def _status(self):
        return summary(call("agent", self.http), call("compte", self.http), call("preparation", self.http))

    def _work(self, word):
        try:
            self._ensure()
            if word == "cherche":
                running = call("agent", self.http).get("etat") in ("en-cours", "arret-demande")
                call("arreter" if running else "demarrer", self.http)
                title = "Recherche arrêtée" if running else "Recherche lancée"
            elif word == "offres":
                if self.open_url is not None:
                    self.open_url(BASE + "/")
                title = "Offres ouvertes"
            else:
                title = "Candidature"
            self._q.put(("ok", title, self._status()))
        except CvgenError as e:
            self._q.put(("error", str(e)))
        except Exception as e:                 # jamais d'exception qui remonte : la carte le dit
            log.exception("cvgen")
            self._q.put(("error", f"Erreur inattendue ({type(e).__name__})"))

    # ---- boucle principale ----
    def ask(self, word, t):
        if self.busy:
            self._show("Candidature", ["Patiente : la demande d'avant n'est pas finie"], t)
            return
        self.busy = True
        self._show("Candidature", ["Je demande à CVGEN…"], t)
        threading.Thread(target=self._work, args=(word,), name="cvgen", daemon=True).start()

    def _show(self, title, lines, t, meta=None):
        self.title, self.lines = title, list(lines)
        self.meta = meta or " · ".join(f"« {w} »" for w in WORDS) + " · " + CLOSE_HINT
        self.show_until = t + SHOW_S

    def events(self, core, t):
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "wait":
                self._show("Candidature", [msg[1]], t)
            elif msg[0] == "ok":
                self.busy = False
                self._show(msg[1], msg[2], t)
                core.last_gesture = (f"CANDIDATURE : {msg[1]}".upper()[:60], t)
            elif msg[0] == "error":
                self.busy = False
                self._show("Candidature impossible", [msg[1]], t)
                core.last_gesture = (f"CANDIDATURE : {msg[1]}".upper()[:60], t)
        return []

    def actions(self, acts, core, t):
        rest = []
        for a in acts:
            if a[0] == "cand":
                self.ask(a[1], t)
            elif a[0] == "cand_off":
                self.lines = None
            elif a[0] in ("rappel_merci", "ask_close") and self.lines is not None:
                self.lines = None              # « iris merci » / « iris ferme » : la carte se ferme
                rest.append(a)
            else:
                rest.append(a)
        return rest

    def state(self, t):
        if self.lines is None or (t >= self.show_until and not self.busy):
            return None
        return {"title": self.title, "lines": list(self.lines), "meta": self.meta}
