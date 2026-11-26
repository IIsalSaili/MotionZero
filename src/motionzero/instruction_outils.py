"""« iris instruction » (#45) : une phrase libre -> Whisper -> modèle local (Ollama) -> plan d'actions d'Iris : méthodes de Instructeur (OutilsMixin, découpé de instruction.py, #52)."""
import logging
import time
import urllib.parse
import urllib.request

from .instruction_base import STEP_PAUSE_S
from .instruction_base2 import youtube_first, youtube_latest

log = logging.getLogger("motionzero.instruction")


class OutilsMixin:

    # ---- fil « instruction-exec » ----
    def _execute(self, plan):
        for i, (outil, arg, label) in enumerate(plan):
            if self._cancel.is_set():
                self._q.put(("step", i, "arrêté"))
                break
            self._q.put(("step", i, "en cours"))
            try:
                out = self.runner(outil, arg)
                self._q.put(("step", i, f"fait : {out}" if isinstance(out, str) and out else "fait"))
            except Exception as e:
                log.exception("instruction : etape %s", label)
                self._q.put(("step", i, f"échec ({str(e)[:40]})"))
                self._q.put(("done", False, None))
                return
            if i < len(plan) - 1:
                time.sleep(STEP_PAUSE_S)
        self._q.put(("done", not self._cancel.is_set(), None))

    def _run_tool(self, outil, arg):
        if outil in ("ouvre_app", "ferme_app"):
            from .apps import close_entry, open_entry
            appid = self.launcher.all.get(arg) if self.launcher is not None else None
            err = (open_entry if outil == "ouvre_app" else close_entry)(arg, appid)
            if err:
                raise RuntimeError(err)
        elif outil == "site":
            if isinstance(arg, tuple):
                from .outils import find_site
                url, searched = find_site(arg[1], self.favoris)
                self.open_url(url)
                if searched and self.favoris is not None:
                    self.favoris.put(arg[1], url)        # retenu : la prochaine fois, ouvert directement
                return url
            self.open_url(arg)
        elif outil == "recherche_web":
            self.open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(arg))
        elif outil == "youtube":
            self.open_url(youtube_first(arg))
        elif outil == "youtube_chaine":
            self.open_url(youtube_latest(arg))
        elif outil == "touche":
            from .output import VK
            from .typer import _key, _send_inputs
            vks = [VK[k] for k in arg]
            _send_inputs([_key(v, False) for v in vks] + [_key(v, True) for v in reversed(vks)])
        elif outil == "ecris":
            from .typer import type_text
            type_text(arg)
        elif outil == "volume":
            from .volume import WindowsVolume
            WindowsVolume().apply(arg)
        elif outil == "timer":
            self.desk.submit_timer(arg)        # texte au lieu du son : Asker._transcribe le rend tel quel
        elif outil == "rappel":
            self.desk.submit(arg, confirm=False)   # plan déjà validé (ou direct) : pas de 2e « envoie »
        elif outil in ("discord", "traducteur", "chronometre"):
            self._q.put(("main", outil, arg))  # état tenu par la boucle principale
        elif outil == "attends":
            time.sleep(arg)
        else:
            return self._run_more(outil, arg)

    def _run_more(self, outil, arg):
        from . import outils as o
        if outil == "cree_routine":
            name, steps = arg
            self.routines.put(name, steps)
            return f"routine « {name} » retenue"
        if outil == "oublie_routine":
            self.routines.remove(arg)
            return None
        if outil == "recherche":
            self.open_url(arg)
        elif outil in ("historique", "historique_video"):
            self.open_url(o.from_history(arg, video=outil == "historique_video"))
        elif outil in ("onglet", "ferme_onglets", "rouvre_onglet", "video"):
            if not o.front("chrome.exe"):
                raise RuntimeError("Chrome n'est pas ouvert")
            time.sleep(0.2)
            if outil == "onglet":
                if not o.find_tab(arg):
                    raise RuntimeError("onglet introuvable")
            elif outil == "ferme_onglets":
                n = 0
                while n < 10 and o.find_tab(arg):
                    o.send_keys(["ctrl", "w"])
                    n += 1
                    time.sleep(0.3)
                return f"{n} onglet(s) fermé(s)"
            elif outil == "rouvre_onglet":
                o.send_keys(["ctrl", "shift", "t"])
            else:
                o.send_keys(arg)
        elif outil == "musique":
            o.send_vk(arg)
        elif outil in ("devant", "fenetre"):
            from .apps import find_window
            from .vscode import bring_to_front
            name = arg if outil == "devant" else arg[0]
            appid = self.launcher.all.get(name, "") if self.launcher is not None else ""
            hwnd = find_window(name, appid)
            if not hwnd or not bring_to_front(hwnd):
                raise RuntimeError(f"{name} n'est pas ouvert")
            if outil == "fenetre":
                time.sleep(0.3)
                o.snap(arg[1])
        elif outil == "meteo":
            return o.weather(arg)
        elif outil == "heure_ville":
            return o.time_in(arg)
        elif outil == "calcul":
            return o.calc(arg)
        elif outil == "conversion":
            try:
                return o.convert(arg)
            except ValueError:
                return o.money(arg)
        elif outil == "agenda":
            self._q.put(("main", "agenda", ""))
        elif outil in ("discord_salon", "discord_message"):
            bot = self.bot
            if bot is None or not bot.connected:
                raise RuntimeError("bot Discord absent")
            msg = {"t": "move", "channel": arg} if outil == "discord_salon" else {"t": "send", "text": arg}
            if bot.send(msg) is None:
                raise RuntimeError("bot Discord occupé")
        elif outil.startswith("discord_"):            # membres, raccrocher (MEMBER_TOOLS)
            bot = self.bot
            if bot is None or not bot.connected:
                raise RuntimeError("bot Discord absent")
            if bot.send({"t": "member", **arg}) is None:
                raise RuntimeError("bot Discord occupé")
        else:
            raise RuntimeError(f"outil sans action : {outil}")
        return None
