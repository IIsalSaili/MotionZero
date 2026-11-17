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
import urllib.parse
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
    "offres": ("GET", "/api/offres"),
    "maj_offre": ("PATCH", "/api/offres/{id}"),     # garder / écarter : comme les boutons de la page Offres
}

# Mots du mode (sans « iris » tant qu'il est allumé). Tous présents dans le modèle Vosk (vérifié le 17/11).
WORDS = {"cherche": "lance ou arrête la recherche",
         "état": "où en est CVGEN",
         "offres": "la page des offres",
         # phase 2 : une offre à la fois sur la carte
         "liste": "les offres à trier puis à vérifier, une par une",
         "suivante": "offre suivante", "précédente": "offre précédente",
         "garde": "garder l'offre (CVGEN prépare le CV)", "écarte": "écarter l'offre",
         "lien": "l'offre sur son site"}
NAV = {"suivante", "précédente", "garde", "écarte", "lien"}   # n'ont de sens que liste ouverte
# à trier d'abord (verdict à donner), puis à vérifier (CV prêt) ; meilleure note en tête
A_PARCOURIR = {"a-trier": "à trier", "generee": "à vérifier"}
NAV_HINT = "« suivante » · « précédente » · « garde » · « écarte » · « lien »"

ETATS = (("verif", "à vérifier"), ("tri", "à trier"), ("ok", "postulées"), ("ref", "refusées"))


class CvgenError(Exception):
    """Message court, affichable tel quel."""


def _http(method, path, body=None, base=BASE, timeout=TIMEOUT_S):
    data = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(base + path, method=method, data=data,
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


def call(name, http=_http, body=None, **ids):
    method, path = ROUTES[name]
    path = path.format(**{k: urllib.parse.quote(str(v), safe="") for k, v in ids.items()})
    return http(method, path, body) if body is not None else http(method, path)


def a_parcourir(offres):
    """Offres à trier puis à vérifier, meilleure note en tête. Pur : testable."""
    def note(o):
        return (o.get("evaluation") or {}).get("globale") or 0
    out = [o for o in offres or [] if o.get("etat") in A_PARCOURIR]
    return sorted(out, key=lambda o: (list(A_PARCOURIR).index(o["etat"]), -note(o)))


def fmt_note(v):
    if not isinstance(v, (int, float)):
        return "?"
    return (f"{v:.1f}".rstrip("0").rstrip(".")).replace(".", ",")


def card(offres, i):
    """(titre, lignes) de l'offre i. Pur : testable."""
    if not offres:
        return "Aucune offre à trier ni à vérifier", ["« cherche » pour en trouver"]
    o = offres[i]
    ev = o.get("evaluation") or {}
    total = sum(1 for x in offres if x["etat"] == o["etat"])
    k = sum(1 for x in offres[:i + 1] if x["etat"] == o["etat"])
    title = f"Offre {k} / {total} {A_PARCOURIR[o['etat']]} · {fmt_note(ev.get('globale'))} / 5"
    lines = [f"{o.get('poste') or 'Poste ?'} · {o.get('entreprise') or 'entreprise ?'}"]
    if ev.get("verdict"):
        lines.append(f"{ev['verdict']} ({o.get('source') or 'site ?'})")
    axes = [a for a in ev.get("axes") or [] if isinstance(a.get("note"), (int, float))]
    if axes:
        fort, faible = max(axes, key=lambda a: a["note"]), min(axes, key=lambda a: a["note"])
        lines.append(f"+ {fort.get('libelle')} : {fort.get('detail', '')}"[:110])
        if faible is not fort:
            lines.append(f"- {faible.get('libelle')} : {faible.get('detail', '')}"[:110])
    return title, lines


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
        self.offres, self.i = None, 0     # liste parcourue (None : pas ouverte) ; seulement boucle principale

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

    def _work(self, word, arg=None):
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
            elif word == "liste":
                self._q.put(("liste", a_parcourir(call("offres", self.http))))
                return
            elif word in ("garde", "écarte"):
                etat = "gardee" if word == "garde" else "ecartee"
                call("maj_offre", self.http, {"etat": etat}, id=arg["id"])
                self._q.put(("verdict", arg["id"], word))
                return
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
        if word in NAV:
            return self._nav(word, t)
        if self.busy:
            self._show("Candidature", ["Patiente : la demande d'avant n'est pas finie"], t)
            return
        self._send(word, t)

    def _send(self, word, t, arg=None):
        self.busy = True
        self._show(self.title or "Candidature", (self.lines or [])[:1] + ["Je demande à CVGEN…"], t, self.meta)
        threading.Thread(target=self._work, args=(word, arg), name="cvgen", daemon=True).start()

    def _nav(self, word, t):
        """Mots de la liste : sans liste ouverte, ils le disent ; garde / écarte passent par CVGEN."""
        if not self.offres:
            self._show("Candidature", ["Pas de liste ouverte : dis « liste »"], t)
            return
        if self.busy:
            self._show(self.title, self.lines[:1] + ["Patiente : la demande d'avant n'est pas finie"], t, self.meta)
            return
        o = self.offres[self.i]
        if word in ("suivante", "précédente"):
            self.i = (self.i + (1 if word == "suivante" else -1)) % len(self.offres)
            self._card(t)
        elif word == "lien":
            if not o.get("url"):
                self._card(t, "Cette offre n'a pas de lien")
            else:
                if self.open_url is not None:
                    self.open_url(o["url"])
                self._card(t, "Ouverte dans le navigateur")
        elif word == "garde" and o["etat"] != "a-trier":
            self._card(t, "Déjà gardée : son CV est prêt")
        else:
            self._send(word, t, o)

    def _card(self, t, note=None):
        title, lines = card(self.offres or [], self.i)
        self._show(title, lines + ([note] if note else []), t, meta=NAV_HINT + " · " + CLOSE_HINT)

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
            elif msg[0] == "liste":
                self.busy = False
                self.offres, self.i = msg[1], 0
                self._card(t)
                core.last_gesture = (f"CANDIDATURE : {len(msg[1])} OFFRES", t)
            elif msg[0] == "verdict":
                self.busy = False
                _, oid, word = msg
                self.offres = [o for o in self.offres or [] if o["id"] != oid]
                self.i = min(self.i, max(len(self.offres) - 1, 0))
                fait = "Gardée : CVGEN prépare son CV" if word == "garde" else "Écartée"
                self._card(t, fait)
                core.last_gesture = (f"CANDIDATURE : {fait}".upper()[:60], t)
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
                self.lines, self.offres = None, None
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
