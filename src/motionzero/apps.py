"""« Iris + nom d'appli » (issue #8).

- La liste des applis vient du menu Démarrer (Get-StartApps : nom + AppID, applis classiques et du Store).
- « iris ouvre » puis le nom, transcrit par Whisper et rapproché de la liste. Jamais « iris + nom » seul :
  trop de risques de déclenchement sur un mot mal entendu.
- Les applis lancées récemment (registre UserAssist de Windows) départagent deux noms proches.
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
import unicodedata
from ctypes import wintypes

log = logging.getLogger("motionzero.apps")
FAVORITES_MAX = 20
FUZZY_MIN = 0.8
RECENT_BONUS = 0.05            # « iris ouvre » : en dessous, rien ne s'ouvre (« PAS COMPRIS »)
NOISE_RE = re.compile(r"uninstall|désinstall|desinstall|documentation|manual|help|aide|readme|release notes|"
                      r"website|visit|learn more|sample|tools for|faq|module docs|support", re.I)
NOISE_EXT = (".url", ".html", ".htm", ".chm", ".pdf", ".msc", ".txt")
# mots qui ne nomment pas l'appli : ignorés dans le rapprochement
FILLER = {"microsoft", "windows", "google", "app", "desktop", "launcher", "client", "the", "de", "du", "la", "le",
          "des", "for", "x64", "x86", "64", "bit", "of", "gx", "center", "light", "launcher"}
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


def build():
    """(toutes, récentes) : toutes = {nom: AppID} ; récentes = noms lancés le plus récemment d'abord."""
    apps = list_start_apps()
    by_id = {appid: name for name, appid in apps.items()}
    ranked = sorted(((t, by_id[k]) for k, t in recent_appids().items() if k in by_id), reverse=True)
    recent = list(dict.fromkeys(n for _, n in ranked))[:FAVORITES_MAX]
    log.info("applis : %d au menu Demarrer, recentes : %s", len(apps), ", ".join(recent))
    return apps, recent


def best_match(text, apps, recent=()):
    """« iris ouvre » : l'appli dont le nom ressemble le plus au texte entendu, ou None si pas assez sûr.
    Les applis lancées récemment ont un petit bonus (départage deux noms proches)."""
    said = re.sub(r"^(?:le|la|les|l|un|une|mon|ma|mes)\s+", "", norm(text))   # « la calculatrice »
    if not said:
        return None
    best, score = None, 0.0
    for name in apps:
        n = norm(name)
        short = " ".join(w for w in n.split() if w not in FILLER)
        s = max(difflib.SequenceMatcher(None, said, n).ratio(), difflib.SequenceMatcher(None, said, short).ratio())
        if len(said) >= 5 and (short + " ").startswith(said + " "):
            s = max(s, 0.9)          # début du nom : « explorateur » = Explorateur de fichiers
        if name in recent:
            s += RECENT_BONUS
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


def close_entry(name, appid):
    """Ferme l'appli comme la croix de sa fenêtre (WM_CLOSE : elle peut demander d'enregistrer)."""
    hwnd = find_window(name, appid)
    if not hwnd:
        return f"{norm(name).upper()} N'EST PAS OUVERT"
    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    log.info("%s fermee", name)
    return None


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
    """« iris ouvre » : liste des applis construite en arrière-plan au démarrage, ouvertures dans un fil à part."""

    def __init__(self, asker, on_message):
        import threading
        self.all, self.recent = {}, []
        self.asker, self.on_message = asker, on_message
        self.threading = threading

        def load():
            try:
                self.all, self.recent = build()
            except Exception:
                log.exception("liste des applis impossible")
        threading.Thread(target=load, name="applis", daemon=True).start()

    def open_spoken(self, audio):
        self.threading.Thread(target=self._spoken, args=(audio, self._open), name="ouvre", daemon=True).start()

    def close_spoken(self, audio):
        self.threading.Thread(target=self._spoken, args=(audio, self._close), name="ferme", daemon=True).start()

    def _close(self, name, appid):
        try:
            err = close_entry(name, appid)
        except Exception as exc:
            log.exception("fermeture de %s", name)
            err = f"{norm(name).upper()} : ECHEC ({exc})"[:60]
        self.on_message(err or f"{norm(name).upper()} FERME")

    def _open(self, name, appid):
        try:
            err = open_entry(name, appid)
        except Exception as exc:
            log.exception("ouverture de %s", name)
            err = f"{norm(name).upper()} : ECHEC ({exc})"[:60]
        self.on_message(err or norm(name).upper())

    def _open_spoken(self, audio):
        self._spoken(audio, self._open)

    def _spoken(self, audio, action):
        try:
            text = self.asker._transcribe(audio, 16000)
        except Exception:
            log.exception("transcription ouvre")
            text = ""
        if not self.all:
            self.on_message("LISTE DES APPLIS PAS PRETE")
            return
        name = best_match(text, self.all, self.recent) if text else None
        if not name:
            self.on_message(f"PAS COMPRIS : {text.strip(' .') or 'rien entendu'}"[:60])
            return
        action(name, self.all[name])
