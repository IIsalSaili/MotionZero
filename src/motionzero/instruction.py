"""« iris instruction » (#45) : une phrase libre -> Whisper -> modèle local (Ollama) -> plan d'actions d'Iris.

Le modèle ne fait rien lui-même : il choisit dans un catalogue FERMÉ d'outils écrits ici. Le plan est vérifié
(outil connu, argument valide), affiché en haut de l'écran, et exécuté seulement après « envoie ».
« annule » l'abandonne ; « stop » arrête un plan en cours entre deux étapes.

Fils : la transcription et le modèle tournent dans le fil « instruction », l'exécution dans « instruction-exec ».
Ils ne rendent compte que par la queue `_q`, lue par events() dans la boucle principale (jamais Core ailleurs).
"""
import logging
import os
import queue
import threading
import time
from .instruction_base import (BLOCKED_APPS, BLOCKED_TEXT, CLOSE_HINT, CONFIRM_S, DIRECT, EXPANDING, HELP_HINT, HELP_S, HELP_WORDS, KEEP_ALIVE, KEY_NAMES, LLM_TIMEOUT_S, MAX_STEPS, MODEL, OLLAMA, OLLAMA_FLAGS, PlanError, SAFE_COMBOS, SAFE_SINGLE, SCHEMA, SHOW_DONE_S, STEP_PAUSE_S, SYSTEM, TOOLS, UA, _app, _http, check_step, ensure_ollama, is_help, normalize_url, parse_keys)  # noqa: F401
from .instruction_base2 import (ask_local, warm_local, _check_more, _get, check_plan, check_plan_raw, expand, first_video_id, youtube_first, youtube_latest)  # noqa: F401
from .instruction_outils import OutilsMixin

log = logging.getLogger("motionzero.instruction")


# ---------------------------------------------------------------- orchestration
class Instructeur(OutilsMixin):
    """submit(audio) depuis la boucle ; events / actions / state appelés par la boucle principale seulement."""

    def __init__(self, transcribe, launcher=None, desk=None, ask=ask_local, open_url=None, runner=None,
                 routines=None, favoris=None, bot=None, warm=warm_local):
        self.transcribe, self.launcher, self.desk, self.ask = transcribe, launcher, desk, ask
        self._warm, self._warming = warm, threading.Lock()
        self.routines, self.favoris, self.bot = routines, favoris, bot    # outils.Store (routines.json, favoris.json)
        self.last_raw = None      # étapes brutes de la dernière instruction réussie (« refais »)
        self._pending_raw = None
        self.open_url = open_url or os.startfile
        self.runner = runner or self._run_tool
        self._q = queue.Queue()
        self.phrase = ""
        self.plan = None          # [(outil, arg, libellé)] en attente d'« envoie »
        self.lines = None         # lignes de la carte en haut
        self.title = ""
        self.show_until = -1e9
        self.busy = False         # un plan s'exécute
        self._cancel = threading.Event()

    # ---- fil « instruction » : Whisper puis modèle ----
    def submit(self, audio):
        threading.Thread(target=self._think, args=(audio,), name="instruction", daemon=True).start()

    def warm(self):
        """« iris instruction » entendu : précharge le modèle pendant que l'utilisateur parle (#76)."""
        threading.Thread(target=self._warm_once, name="instruction-warm", daemon=True).start()

    def _warm_once(self):
        if not self._warming.acquire(blocking=False):     # déjà en cours
            return
        try:
            t0 = time.perf_counter()
            ok = self._warm()
            log.info("instruction : modele precharge=%s en %.1f s", ok, time.perf_counter() - t0)
        except Exception:
            log.exception("instruction : prechargement")
        finally:
            self._warming.release()

    def _think(self, audio):
        t0 = time.perf_counter()
        try:
            phrase = (self.transcribe(audio) or "").strip(" .")
        except Exception:
            log.exception("transcription instruction")
            phrase = ""
        if not phrase:
            self._q.put(("error", "", "rien entendu"))
            return
        if is_help(phrase):                   # sans le modèle : toujours la même réponse, tout de suite
            self._q.put(("help",))
            return
        t1 = time.perf_counter()
        try:
            raw = self.ask(phrase + self._context())
            log.info("instruction : transcription %.1f s, modele %.1f s", t1 - t0, time.perf_counter() - t1)
            names = self.launcher.all if self.launcher is not None and self.launcher.all else None
            plan, flat = check_plan_raw(raw, names, {"routines": self.routines, "favoris": self.favoris,
                                                     "last": self.last_raw})
        except PlanError as e:
            log.info("instruction refusee : %s -> %s", phrase, e)
            self._q.put(("error", phrase, str(e)))
            return
        except Exception as e:
            log.exception("instruction : modele")
            self._q.put(("error", phrase, str(e) if isinstance(e, RuntimeError) else "réponse du modèle illisible"))
            return
        if any(o == "aide" for o, _, _ in plan):
            self._q.put(("help",))
            return
        log.info("instruction : %s -> %s", phrase, [lbl for _, _, lbl in plan])
        self._q.put(("plan", phrase, plan, flat))

    def _context(self):
        """Noms connus, donnés au modèle avec la demande (il ne peut pas les deviner)."""
        parts = []
        if self.routines is not None and self.routines.names():
            parts.append("Routines connues : " + ", ".join(self.routines.names()))
        if self.favoris is not None and self.favoris.names():
            parts.append("Sites déjà retenus (outil site avec ce nom) : " + ", ".join(self.favoris.names()))
        return ("\n\n" + "\n".join(parts)) if parts else ""

    # ---- boucle principale ----
    def events(self, core, t):
        """Résultats des fils ; renvoie les actions à faire par la boucle (Discord…)."""
        acts = []
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                break
            kind = msg[0]
            if kind == "error":
                self.plan, self.title, self.meta = None, "Instruction impossible", CLOSE_HINT
                self.lines = ([f"« {msg[1]} »"] if msg[1] else []) + [msg[2], HELP_HINT]
                self.show_until = t + SHOW_DONE_S
                core.last_gesture = (f"INSTRUCTION : {msg[2]}".upper()[:60], t)
                self._say(f"Instruction impossible : {msg[2]}")
            elif kind == "help":
                from .outils import EXAMPLES
                self.plan, self.title = None, "Dis « iris instruction », puis par exemple :"
                self.lines = list(EXAMPLES)
                self.meta = CLOSE_HINT
                self.show_until = t + HELP_S
            elif kind == "plan":
                self.phrase, self.plan = msg[1], msg[2]
                self._pending_raw = msg[3] if len(msg) > 3 else None
                self.lines = [f"{i + 1}. {lbl}" for i, (_, _, lbl) in enumerate(self.plan)]
                if not self.busy and all(o in DIRECT for o, _, _ in self.plan):
                    self._start(core, t)          # ouvre, timer, rappel, volume, message, salon, chrono : direct
                    continue
                self.title, self.meta = "Dis « envoie » pour le faire", None
                self.show_until = t + CONFIRM_S
                core.ask_confirm("instruction", t, CONFIRM_S)
            elif kind == "step":
                i, status = msg[1], msg[2]
                if self.lines and i < len(self.lines):
                    base = self.lines[i].split(" — ")[0]
                    self.lines[i] = f"{base} — {status}"
                self.show_until = t + SHOW_DONE_S
            elif kind == "done":
                self.busy = False
                if msg[1] and getattr(self, "_running_raw", None):
                    self.last_raw = self._running_raw        # « refais » rejoue celle-ci
                self.title = "Instruction faite" if msg[1] else "Instruction interrompue"
                self._say(self.title)
                self.meta = CLOSE_HINT
                self.show_until = t + SHOW_DONE_S
            elif kind == "main":
                if msg[1] == "discord":
                    acts.append((msg[2],))
                elif msg[1] == "chronometre":
                    acts.append(("chrono",))
                elif msg[1] == "traducteur":
                    core._cmd_translator("traducteur", t, acts)
                elif msg[1] == "agenda" and self.desk is not None:
                    self.desk._result(core, t, self.desk.clock(), "list", None)
        if self.plan is not None and not core.confirming(t) and not self.busy and t >= self.show_until:
            self.plan = None                   # pas de réponse : plan abandonné
        return acts

    def _say(self, text):
        """Lu seulement si « lecture à voix haute » est cochée (Speaker.allowed)."""
        sp = getattr(self, "speaker", None)
        try:
            if sp is not None:
                sp.say(text, force=True)
        except Exception:
            log.exception("lecture instruction")

    def _start(self, core, t):
        """Lance le plan en attente dans le fil « instruction-exec » (boucle principale seulement)."""
        plan, self.plan = self.plan, None
        self._running_raw = self._pending_raw
        self.busy = True
        self.title, self.meta = "Instruction en cours", "« stop » : arrêter"
        self.show_until = t + SHOW_DONE_S
        self._cancel = threading.Event()
        threading.Thread(target=self._execute, args=(plan,), name="instruction-exec", daemon=True).start()
        core.last_gesture = ("INSTRUCTION LANCEE", t)

    def actions(self, acts, core, t):
        rest = []
        for a in acts:
            if a[0] == "instruction_ok":
                if self.plan is None or self.busy:
                    continue
                self._start(core, t)
            elif a[0] in ("rappel_merci", "ask_close") and not self.busy and self.lines is not None:
                # « iris merci » / « iris ferme » : la carte se ferme ; un plan en attente est abandonné (rien fait)
                if self.plan is not None:
                    core.confirm_until = -1e9
                self.plan, self.lines = None, None
                rest.append(a)
            elif a[0] == "instruction_non":
                self.plan, self.lines = None, None
                core.last_gesture = ("INSTRUCTION ABANDONNEE", t)
            else:
                if a[0] == "release_all" and self.busy:   # « stop » : arrêt entre deux étapes
                    self._cancel.set()
                rest.append(a)
        return rest

    def state(self, t):
        """Carte du haut : None ou {"title", "lines"}."""
        if self.lines is None or (t >= self.show_until and not self.busy and self.plan is None):
            return None
        return {"title": self.title, "lines": list(self.lines), "meta": getattr(self, "meta", None)}
