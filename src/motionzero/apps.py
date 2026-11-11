"""« Iris + nom d'appli » (issue #8).

- La liste des applis vient du menu Démarrer (Get-StartApps : nom + AppID, applis classiques et du Store).
- Les favorites (commandes directes, rapides) : les applis lancées le plus récemment, d'après le registre
  UserAssist de Windows, dont le nom est connu de la reconnaissance vocale.
- Toutes les autres : « iris ouvre » puis le nom, transcrit par Whisper et rapproché de la liste.
- Lancement : shell:AppsFolder\\<AppID> (même méthode pour toutes). Si l'appli est déjà ouverte : premier plan.
"""
import codecs
import ctypes
import datetime
import difflib
import json
import logging
import os
import re
import struct
import subprocess
import sys
import unicodedata
from ctypes import wintypes

log = logging.getLogger("motionzero.apps")
FAVORITES_MAX = 20
FUZZY_MIN = 0.8            # « iris ouvre » : en dessous, rien ne s'ouvre (« PAS COMPRIS »)
NOISE_RE = re.compile(r"uninstall|désinstall|desinstall|documentation|manual|help|aide|readme|release notes|"
                      r"website|visit|learn more|sample|tools for|faq|module docs|support", re.I)
NOISE_EXT = (".url", ".html", ".htm", ".chm", ".pdf", ".msc", ".txt")
# mots qui ne nomment pas l'appli : retirés pour trouver un nom court à dire
FILLER = {"microsoft", "windows", "google", "app", "desktop", "launcher", "client", "the", "de", "du", "la", "le",
          "des", "for", "x64", "x86", "64", "bit", "of", "gx", "center", "light", "launcher"}
# premier mot trop vague pour être dit seul : seulement dans le nom en deux mots (« bloc notes », « game bar »)
GENERIC = {"game", "lecteur", "navigateur", "mobile", "bloc", "outil", "gigabyte", "centre", "gestion", "store",
           "battle", "editeur", "éditeur", "invite", "connexion", "assistance", "sécurité", "panneau"}
# déjà des commandes, ou trop proches d'autres commandes / de la conversation
RESERVED = {"chrome", "discord", "studio", "home", "code", "claude", "type", "question", "ferme", "souris", "lecture",
            "pause", "stop", "clic", "double", "menu", "glisse", "lâche", "défile", "entrée", "espace", "space",
            "annule", "copie", "colle", "envoie", "tab", "mute", "ouvre", "iris", "notes", "photos", "word", "zoom",
            "musique"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s):
    """Nom comparable : minuscules, sans accents, sans ponctuation ni numéros de version."""
    s = re.sub(r"\(.*?\)|®|™", " ", s.lower())
    s = re.sub(r"[^\w\s]", " ", strip_accents(s))
    return " ".join(w for w in s.split() if not re.fullmatch(r"\d[\d.]*", w))


def list_start_apps():
    """{nom affiché: AppID} des applis du menu Démarrer, sans désinstalleurs, docs ni liens web."""
    cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=30,
                         creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    data = json.loads(out or "[]")
    apps = {}
    for e in data if isinstance(data, list) else [data]:
        name, appid = e.get("Name", ""), e.get("AppID", "")
        if (not name or "://" in appid or appid.lower().endswith(NOISE_EXT) or NOISE_RE.search(name)
                or appid.startswith(("C:\\", "c:\\"))):
            continue
        apps.setdefault(name, appid)
    return apps


def recent_appids():
    """AppID -> dernier lancement (registre UserAssist : menu Démarrer, barre des tâches, raccourcis)."""
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
    seen = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            try:
                ck = winreg.OpenKey(k, guid + r"\Count")
            except OSError:
                continue
            j = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(ck, j)
                except OSError:
                    break
                j += 1
                if not isinstance(val, bytes) or len(val) < 68:
                    continue
                ft = struct.unpack_from("<Q", val, 60)[0]
                if not ft:
                    continue
                t = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
                key = codecs.decode(name, "rot13")
                seen[key] = max(seen.get(key, t), t)
    return seen


def spoken(name):
    """Mots du nom tels que le modèle vocal les connaît : minuscules, accents gardés, sans ponctuation."""
    s = re.sub(r"\(.*?\)|®|™", " ", name.lower())
    return [w for w in re.sub(r"[^\w\s]", " ", s).split()
            if not re.fullmatch(r"\d[\d.]*", w) and strip_accents(w) not in FILLER]


def aliases(name):
    """Façons de dire le nom : les deux premiers mots utiles (« bloc notes ») ; le premier seul s'il est
    distinctif (« steam », « whatsapp », « explorateur »)."""
    words = spoken(name)
    out = []
    if len(words) >= 2:
        out.append(" ".join(words[:2]))
    if words and words[0] not in GENERIC:
        out.append(words[0])
    return [a for a in dict.fromkeys(out) if a and a not in RESERVED and len(a) >= 3]


def missing_words(model_dir, words):
    """Mots absents du vocabulaire Vosk (le modèle l'écrit dans son journal ; mesuré dans un processus à part)."""
    code = ("import json,sys\nfrom vosk import Model,KaldiRecognizer,SetLogLevel\nSetLogLevel(0)\n"
            "m=Model(sys.argv[1])\nKaldiRecognizer(m,16000,json.dumps(json.load(sys.stdin),ensure_ascii=False))\n")
    out = subprocess.run([sys.executable, "-c", code, model_dir], input=json.dumps(sorted(words) + ["[unk]"]),
                         capture_output=True, text=True, encoding="utf-8", timeout=60, creationflags=NO_WINDOW)
    return set(re.findall(r"missing in vocabulary\W+(\S+?)['\"]?\s*$", out.stderr, re.M)) | \
        set(re.findall(r"Ignoring word missing in vocabulary: '([^']+)'", out.stderr))


def build(model_dir):
    """(favorites, toutes) : favorites = {mot ou phrase à dire: (nom, AppID)} ; toutes = {nom: AppID}."""
    apps = list_start_apps()
    recent = recent_appids()
    by_id = {appid: name for name, appid in apps.items()}
    ranked = sorted(((t, by_id[k]) for k, t in recent.items() if k in by_id), reverse=True)
    names = list(dict.fromkeys(n for _, n in ranked))
    cand = {n: aliases(n) for n in names}
    missing = missing_words(model_dir, {w for al in cand.values() for a in al for w in a.split()})
    fav = {}
    for n in names:
        ok = [a for a in cand[n] if not set(a.split()) & missing and a not in fav]
        for a in ok:
            fav[a] = (n, apps[n])
        if len({v[0] for v in fav.values()}) >= FAVORITES_MAX:
            break
    log.info("applis : %d au menu Demarrer, favorites : %s", len(apps), ", ".join(sorted(fav)))
    return fav, apps


def best_match(text, apps):
    """« iris ouvre » : l'appli dont le nom ressemble le plus au texte entendu, ou None si pas assez sûr."""
    said = norm(text)
    if not said:
        return None
    best, score = None, 0.0
    for name in apps:
        n = norm(name)
        short = " ".join(w for w in n.split() if w not in FILLER)
        s = max(difflib.SequenceMatcher(None, said, n).ratio(), difflib.SequenceMatcher(None, said, short).ratio())
        if s > score:
            best, score = name, s
    log.info("ouvre : '%s' -> %s (%.2f)", text, best, score)
    return best if score >= FUZZY_MIN else None


# --- fenêtre déjà ouverte ? ------------------------------------------------------------------------
def _window_aumid(hwnd):
    try:
        from win32com.propsys import propsys, pscon
        store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
        return str(store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue() or "")
    except Exception:
        return ""


def find_window(name, appid):
    """Fenêtre principale de l'appli : même AppID, sinon même exe, sinon le nom dans le titre."""
    from .vscode import _exe_of, _title_of
    u = ctypes.windll.user32
    exe = os.path.basename(appid).lower() if appid.lower().endswith(".exe") else None
    short = norm(name)
    hits = {"aumid": None, "exe": None, "title": None}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd) or not u.GetWindowTextLengthW(hwnd) or u.GetWindow(hwnd, 4):
            return True
        if _window_aumid(hwnd).lower() == appid.lower():
            hits["aumid"] = hwnd
            return False
        if exe and not hits["exe"] and _exe_of(hwnd) == exe:
            hits["exe"] = hwnd
        if not hits["title"] and short and norm(_title_of(hwnd)).endswith(short):
            hits["title"] = hwnd
        return True

    u.EnumWindows(cb, 0)
    return hits["aumid"] or hits["exe"] or hits["title"]


def open_entry(name, appid):
    """Premier plan si ouverte, sinon lancement. Renvoie None ou un message d'erreur pour l'île."""
    from .vscode import bring_to_front
    label = norm(name).upper()
    hwnd = find_window(name, appid)
    if hwnd:
        if not bring_to_front(hwnd):
            return f"{label} PAS AU PREMIER PLAN"
        log.info("%s au premier plan", name)
        return None
    try:
        os.startfile("shell:AppsFolder\\" + appid)
    except OSError:
        log.warning("%s introuvable (%s)", name, appid)
        return f"{label} INTROUVABLE"
    log.info("%s lance", name)
    return None


class Launcher:
    """Liste des applis (construite en arrière-plan au démarrage) et ouvertures, dans un fil à part."""

    def __init__(self, model_dir, asker, on_ready, on_message):
        import threading
        self.fav, self.all = {}, {}
        self.asker, self.on_message = asker, on_message
        self.threading = threading

        def load():
            try:
                self.fav, self.all = build(model_dir)
                on_ready(sorted(self.fav))
            except Exception:
                log.exception("liste des applis impossible")
        threading.Thread(target=load, name="applis", daemon=True).start()

    def _bg(self, fn, *args):
        self.threading.Thread(target=fn, args=args, name="ouvre", daemon=True).start()

    def open_favorite(self, word):
        if word in self.fav:
            self._bg(self._open, *self.fav[word])

    def open_spoken(self, audio):
        self._bg(self._open_spoken, audio)

    def _open(self, name, appid):
        try:
            err = open_entry(name, appid)
        except Exception as exc:
            log.exception("ouverture de %s", name)
            err = f"{norm(name).upper()} : ECHEC ({exc})"[:60]
        self.on_message(err or norm(name).upper())

    def _open_spoken(self, audio):
        try:
            text = self.asker._transcribe(audio, 16000)
        except Exception:
            log.exception("transcription ouvre")
            text = ""
        name = best_match(text, self.all) if text else None
        if not name:
            self.on_message(f"PAS COMPRIS : {text.strip(' .') or 'rien entendu'}"[:60])
            return
        self._open(name, self.all[name])
