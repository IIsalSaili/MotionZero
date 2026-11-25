"""Outils supplémentaires d'« iris instruction » (#45) : routines, favoris, vidéo, onglets, historique, infos, : constantes et fonctions (1/2, découpé de outils.py, #52)."""
import ast
import ctypes
import datetime
import glob
import json
import logging
import operator
import os
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
import urllib.request

log = logging.getLogger("motionzero.outils")


# ---------------------------------------------------------------- petits magasins JSON d'Iris
class Store:
    """Dictionnaire nom -> valeur gardé dans un fichier JSON d'Iris (écriture atomique)."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def get(self, name):
        return self.data.get(norm_name(name))

    def put(self, name, value):
        self.data[norm_name(name)] = value
        self.save()

    def remove(self, name):
        if self.data.pop(norm_name(name), None) is None:
            return False
        self.save()
        return True

    def names(self):
        return sorted(self.data)


def norm_name(s):
    from .apps import strip_accents
    return re.sub(r"\s+", " ", strip_accents(s).lower().strip(" .«»\"'"))


def split_pair(arg, seps=("=", "|", "->", ":")):
    """« mes mails = gmail.com » -> (« mes mails », « gmail.com ») ; None si pas de séparateur."""
    for sep in seps:
        if sep in arg:
            a, b = arg.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    return None


# ---------------------------------------------------------------- recherches ciblées (une page, aucun clic)
SEARCH = {"google": "https://www.google.com/search?q={q}",
          "youtube": "https://www.youtube.com/results?search_query={q}",
          "amazon": "https://www.amazon.fr/s?k={q}",
          "maps": "https://www.google.com/maps/search/{q}",
          "itineraire": "https://www.google.com/maps/dir/?api=1&destination={q}",
          "wikipedia": "https://fr.wikipedia.org/w/index.php?search={q}",
          "twitch": "https://www.twitch.tv/search?term={q}",
          "spotify": "https://open.spotify.com/search/{q}",
          "images": "https://www.google.com/search?tbm=isch&q={q}"}


def search_url(arg):
    """« amazon: casque » -> adresse de la page de résultats ; None si le site n'est pas connu."""
    pair = split_pair(arg, (":", "=", "|"))
    if not pair:
        return None
    site, text = norm_name(pair[0]), pair[1]
    site = {"google maps": "maps", "carte": "maps", "itineraire": "itineraire", "wiki": "wikipedia",
            "youtube music": "youtube"}.get(site, site)
    if site not in SEARCH:
        return None
    return SEARCH[site].format(q=urllib.parse.quote_plus(text))


# ---------------------------------------------------------------- vidéo (touches YouTube) et musique (touches média)
VIDEO = {"pause": ["k"], "lecture": ["k"], "plein ecran": ["f"], "avance": ["l"], "recule": ["j"],
         "suivante": ["shift", "n"], "sous-titres": ["c"], "muet": ["m"], "debut": ["0"]}
MEDIA_VK = {"lecture": 0xB3, "pause": 0xB3, "suivant": 0xB0, "precedent": 0xB1}


def video_keys(arg):
    a = norm_name(arg).replace("sous titres", "sous-titres").replace("plein-ecran", "plein ecran")
    return VIDEO.get(a)


def media_vk(arg):
    return MEDIA_VK.get(norm_name(arg).replace("suivante", "suivant").replace("precedente", "precedent"))


def send_keys(keys):
    from .output import VK
    from .typer import _key, _send_inputs
    vks = [VK[k] for k in keys]
    _send_inputs([_key(v, False) for v in vks] + [_key(v, True) for v in reversed(vks)])


def send_vk(vk):
    from .typer import _key, _send_inputs
    _send_inputs([_key(vk, False), _key(vk, True)])


# ---------------------------------------------------------------- fenêtres et onglets (titres seulement)
def front(exe):
    """Met le programme au premier plan ; False s'il n'a pas de fenêtre."""
    from .vscode import bring_to_front, find_app_window
    hwnd = find_app_window(exe)
    return bool(hwnd) and bool(bring_to_front(hwnd))


def front_title():
    from .vscode import _title_of
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return _title_of(hwnd) if hwnd else ""


def find_tab(words, title=front_title, next_tab=lambda: send_keys(["ctrl", "tab"]), max_tabs=30, pause=0.15):
    """Fait défiler les onglets de Chrome (Ctrl+Tab) jusqu'à celui dont le titre contient `words`.
    Seul le titre de la fenêtre est lu : aucune autorisation de plus. True si trouvé."""
    want = norm_name(words)
    seen = []
    for _ in range(max_tabs):
        t = title()
        if want in norm_name(t):
            return True
        if t in seen[:1] and len(seen) > 1:   # revenu au premier onglet : fait le tour
            return False
        seen.append(t)
        next_tab()
        time.sleep(pause)
    return False


def snap(side):
    """Fenêtre au premier plan sur une moitié (Win+flèche, comme « iris gauche / droite ») ou agrandie."""
    if side == "plein":
        from .fenetre import maximize_foreground
        maximize_foreground()
        return
    send_keys(["win", "left" if side == "gauche" else "right"])
    time.sleep(0.3)
    send_keys(["escape"])                     # ferme le choix de la 2e fenêtre proposé par Windows


# ---------------------------------------------------------------- historique de Chrome (lecture seule)
def chrome_history_files():
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    files = [p for p in glob.glob(os.path.join(root, "*", "History"))
             if os.path.basename(os.path.dirname(p)) == "Default" or "Profile" in p]
    return sorted(files, key=os.path.getmtime, reverse=True)


def read_history(path, limit=400):
    """[(titre, adresse, instant)] les plus récents. Copie d'abord le fichier (Chrome le verrouille) :
    l'original n'est jamais ouvert en écriture."""
    tmpdir = tempfile.mkdtemp(prefix="iris-hist-")
    copy = os.path.join(tmpdir, "History")
    try:
        shutil.copy2(path, copy)
        con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT title, url, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT ?",
                               (limit,)).fetchall()
        finally:
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return rows


def pick_history(rows, words, video=False):
    """1re adresse (la plus récente) dont le titre ou l'adresse contient tous les mots. Pur."""
    want = [w for w in norm_name(words).split() if len(w) > 2 and w not in ("video", "regardais", "derniere")]
    for title, url, _ in rows:
        if video and "youtube.com/watch" not in url:
            continue
        hay = norm_name(f"{title} {url}")
        if all(w in hay for w in want):
            return url
    return None


def from_history(words, video=False):
    files = chrome_history_files()
    if not files:
        raise RuntimeError("historique de Chrome introuvable")
    url = pick_history(read_history(files[0]), words, video)
    if not url:
        raise RuntimeError("rien de tel dans l'historique")
    return url


# ---------------------------------------------------------------- infos (lecture seule, affichées)
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def calc(expr):
    """Calcul sûr (jamais eval) : + - * / ^ % parenthèses, « racine de », « pourcent de »."""
    e = norm_name(expr).replace(",", ".").replace("x", "*").replace("fois", "*").replace("plus", "+") \
        .replace("moins", "-").replace("divise par", "/").replace("sur", "/").replace("^", "**")
    e = re.sub(r"(\d+(?:\.\d+)?)\s*(?:%|pour ?cent)\s*de\s*", r"\1/100*", e)
    e = re.sub(r"racine(?: carree)? de\s*(\d+(?:\.\d+)?)", r"(\1)**0.5", e)
    e = e.replace("=", "").strip()
    if not re.fullmatch(r"[\d\s.+\-*/()%]+", e) or len(e) > 80:
        raise ValueError("calcul incompris")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise ValueError("trop grand")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("calcul incompris")
    v = ev(ast.parse(e, mode="eval"))
    return f"{expr.strip()} = {fmt_num(v)}"


def fmt_num(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
    return f"{v:,}".replace(",", " ")


UNITS = {  # unité -> (grandeur, facteur vers l'unité de base)
    "km": ("l", 1000), "m": ("l", 1), "cm": ("l", 0.01), "mm": ("l", 0.001), "mile": ("l", 1609.344),
    "miles": ("l", 1609.344), "pied": ("l", 0.3048), "pieds": ("l", 0.3048), "pouce": ("l", 0.0254),
    "pouces": ("l", 0.0254), "kg": ("w", 1), "g": ("w", 0.001), "livre": ("w", 0.45359237),
    "livres": ("w", 0.45359237), "lb": ("w", 0.45359237), "l": ("v", 1), "litre": ("v", 1), "litres": ("v", 1),
    "ml": ("v", 0.001), "cl": ("v", 0.01), "gallon": ("v", 3.785411784), "gallons": ("v", 3.785411784),
    "km/h": ("s", 1), "mph": ("s", 1.609344), "h": ("t", 3600), "heure": ("t", 3600), "heures": ("t", 3600),
    "min": ("t", 60), "minute": ("t", 60), "minutes": ("t", 60), "s": ("t", 1), "jour": ("t", 86400),
    "jours": ("t", 86400)}


def convert(arg):
    """« 5 miles en km », « 70 °F en °C » -> texte du résultat. ValueError si incompris."""
    m = re.match(r"\s*(-?[\d.,]+)\s*(.+?)\s+(?:en|vers|->)\s+(.+?)\s*$", arg, re.I)
    if not m:
        raise ValueError("conversion incomprise")
    v = float(m.group(1).replace(",", "."))
    a, b = (norm_name(x).replace("degres", "").replace("°", "").strip() for x in m.group(2, 3))
    temps = {"c": "c", "celsius": "c", "f": "f", "fahrenheit": "f"}
    if a in temps and b in temps:
        c = v if temps[a] == "c" else (v - 32) * 5 / 9
        r = c if temps[b] == "c" else c * 9 / 5 + 32
        return f"{fmt_num(v)} °{temps[a].upper()} = {fmt_num(round(r, 1))} °{temps[b].upper()}"
    if a in UNITS and b in UNITS and UNITS[a][0] == UNITS[b][0]:
        r = v * UNITS[a][1] / UNITS[b][1]
        return f"{fmt_num(v)} {m.group(2).strip()} = {fmt_num(round(r, 3))} {m.group(3).strip()}"
    raise ValueError("unités inconnues")


CITY_TZ = {"paris": "Europe/Paris", "londres": "Europe/London", "new york": "America/New_York",
           "montreal": "America/Toronto", "los angeles": "America/Los_Angeles", "tokyo": "Asia/Tokyo",
           "dubai": "Asia/Dubai", "casablanca": "Africa/Casablanca", "alger": "Africa/Algiers",
           "tunis": "Africa/Tunis", "dakar": "Africa/Dakar", "pekin": "Asia/Shanghai", "sydney": "Australia/Sydney",
           "moscou": "Europe/Moscow", "istanbul": "Europe/Istanbul", "berlin": "Europe/Berlin",
           "madrid": "Europe/Madrid", "rome": "Europe/Rome", "bruxelles": "Europe/Brussels",
           "geneve": "Europe/Zurich", "riyad": "Asia/Riyadh", "le caire": "Africa/Cairo", "mumbai": "Asia/Kolkata",
           "sao paulo": "America/Sao_Paulo", "mexico": "America/Mexico_City"}


def time_in(city, now=None):
    from zoneinfo import ZoneInfo
    tz = CITY_TZ.get(norm_name(city))
    if tz is None:
        raise ValueError(f"ville inconnue : {city}")
    t = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(ZoneInfo(tz))
    return f"{city.strip().title()} : {t:%H:%M}"


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Iris/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


WMO = {0: "ciel clair", 1: "plutôt clair", 2: "nuageux par endroits", 3: "couvert", 45: "brouillard",
       48: "brouillard givrant", 51: "bruine", 53: "bruine", 55: "bruine forte", 61: "pluie faible", 63: "pluie",
       65: "forte pluie", 71: "neige faible", 73: "neige", 75: "forte neige", 80: "averses", 81: "averses",
       82: "fortes averses", 95: "orage", 96: "orage et grêle", 99: "orage et grêle"}
