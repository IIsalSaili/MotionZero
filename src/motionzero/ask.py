"""« Iris, question » : la question est enregistrée, transcrite sur le PC (Whisper, carte graphique),
puis posée à Claude Haiku par la ligne de commande de Claude Code (abonnement Pro, sans clé d'API).

Tout le travail lent se fait dans un fil à part : l'appli continue de répondre pendant ce temps.
L'état (écoute / réflexion / réponse / erreur) est lu par l'île pour l'affichage.
"""
import glob
import json
import logging
import os
import subprocess
import threading
import time

import numpy as np


def _nvidia_dlls():
    """Bibliothèques NVIDIA (cuBLAS, cuDNN) installées en paquets Python : Windows ne les trouve pas seul."""
    import site
    for base in site.getsitepackages():
        for d in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

log = logging.getLogger("motionzero.ask")
MODEL = "haiku"
WHISPER = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"   # déjà téléchargé dans le cache
SYSTEM = ("Tu es Iris, une assistante vocale. Tu réponds en français, en trois phrases au maximum, "
          "sans mise en forme (pas de listes, pas de gras, pas de titres). Va droit au but.")
WHISPER_IDLE_S = 600      # inutilisé 10 min : déchargé (rechargé en ~2-3 s à la commande suivante)
WHISPER_CPU_THREADS = 4
ANSWER_S = 15.0          # durée d'affichage de la réponse
CLAUDE_TIMEOUT_S = 60


def find_claude():
    """claude.exe fourni avec l'extension VS Code (la version la plus récente)."""
    pattern = os.path.expandvars(r"%USERPROFILE%\.vscode\extensions\anthropic.claude-code-*-win32-x64"
                                 r"\resources\native-binary\claude.exe")
    found = sorted(glob.glob(pattern), key=lambda p: [int(x) if x.isdigit() else x
                                                     for x in p.replace("-", ".").split(".")])
    return found[-1] if found else None


def ask_claude(question, exe=None):
    """Réponse de Claude Haiku à une question, ou lève RuntimeError."""
    exe = exe or find_claude()
    if not exe:
        raise RuntimeError("Claude Code introuvable")
    cmd = [exe, "-p", question, "--model", MODEL, "--output-format", "json", "--system-prompt", SYSTEM,
           "--tools", "", "--no-session-persistence", "--safe-mode"]
    # --safe-mode : ni hooks (pas de son de notification), ni CLAUDE.md, ni plugins : rapide et léger
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=CLAUDE_TIMEOUT_S,
                         cwd=os.path.expanduser("~"), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        data = json.loads(out.stdout)
    except ValueError:
        raise RuntimeError((out.stderr or out.stdout or "réponse illisible").strip()[:120])
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result", "erreur"))[:120])
    return str(data.get("result", "")).strip()


class Asker:
    """Une question à la fois. Phases : None, « listening », « thinking », « answer », « error »."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase, self.question, self.answer, self.t = None, "", "", 0.0
        self._whisper = None
        self._model_lock = threading.Lock()
        self._used_t = 0.0

    def _set(self, phase, question=None, answer=None):
        with self.lock:
            self.phase, self.t = phase, time.perf_counter()
            if question is not None:
                self.question = question
            if answer is not None:
                self.answer = answer

    def listening(self):
        self._set("listening", question="", answer="")

    def cancel(self):
        self._set(None)

    def close(self):
        self._set(None)

    def submit(self, audio, sr=16000):
        """Lance la transcription puis la question à Claude dans un fil à part."""
        self._set("thinking")
        threading.Thread(target=self._work, args=(audio, sr), name="question", daemon=True).start()

    def preload(self):
        """Charge et échauffe Whisper en arrière-plan (sinon la 1re question attend ~2 s de plus),
        puis le décharge s'il ne sert plus : la carte graphique est rendue aux jeux (~2,3 Go)."""
        threading.Thread(target=self._load, name="whisper", daemon=True).start()
        threading.Thread(target=self._reaper, name="whisper-veille", daemon=True).start()

    def _load(self):
        # un seul chargement à la fois (plusieurs commandes pouvaient charger deux modèles en même temps)
        with self._model_lock:
            if self._whisper is not None:
                return
            from faster_whisper import WhisperModel
            t0 = time.perf_counter()
            try:
                _nvidia_dlls()
                model = WhisperModel(WHISPER, device="cuda", compute_type="float16", local_files_only=True)
                model.transcribe(np.zeros(16000, np.float32), language="fr")   # échauffement (1re passe lente)
                log.info("whisper pret (carte graphique, %.1f s)", time.perf_counter() - t0)
            except Exception:
                log.exception("whisper sur carte graphique impossible : processeur (plus lent)")
                # 4 cœurs au plus : sans limite, la transcription prenait tout le processeur
                model = WhisperModel(WHISPER, device="cpu", compute_type="int8", cpu_threads=WHISPER_CPU_THREADS,
                                     local_files_only=True)
            self._whisper = model
            self._used_t = time.perf_counter()

    def _reaper(self):
        while True:
            time.sleep(30)
            with self._model_lock:
                if self._whisper is not None and time.perf_counter() - self._used_t > WHISPER_IDLE_S:
                    self._whisper = None
                    import gc
                    gc.collect()
                    log.info("whisper decharge (inutilise depuis %d min)", WHISPER_IDLE_S // 60)

    def _transcribe(self, audio, sr):
        self._load()          # rechargé à la demande s'il a été déchargé
        pcm = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        # une transcription à la fois : jamais deux en même temps sur la carte graphique
        with self._model_lock:
            self._used_t = time.perf_counter()
            segments, _ = self._whisper.transcribe(pcm, language="fr", beam_size=1, vad_filter=True)
            text = " ".join(s.text.strip() for s in segments).strip()
            self._used_t = time.perf_counter()
            return text

    def _work(self, audio, sr):
        try:
            question = self._transcribe(audio, sr)
            if not question:
                self._set("error", answer="Je n'ai pas entendu de question.")
                return
            self._set("thinking", question=question)
            log.info("question : %s", question)
            t0 = time.perf_counter()
            answer = ask_claude(question)
            log.info("reponse (%.1f s) : %s", time.perf_counter() - t0, answer)
            self._set("answer", answer=answer)
        except Exception as exc:
            log.exception("question echouee")
            self._set("error", answer=f"Échec : {exc}"[:140])

    def snapshot(self):
        """État pour l'île : dict, ou None si rien à montrer (réponse expirée comprise)."""
        with self.lock:
            if self.phase is None:
                return None
            age = time.perf_counter() - self.t
            if self.phase in ("answer", "error") and age > ANSWER_S:
                self.phase = None
                return None
            return {"phase": self.phase, "question": self.question, "answer": self.answer,
                    "left": max(0.0, ANSWER_S - age)}
