"""Commandes vocales hors ligne (Vosk, petit modèle français, grammaire fermée).

- Seuls les mots de WORDS sont reconnus ; tout le reste devient « [unk] » et est ignoré.
- En veille par défaut : seul le mot de réveil « iris » (ou un geste) ouvre l'écoute quelques secondes.
- Les événements sont horodatés (time.perf_counter) pour être fusionnés avec la position de la main.
"""
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("motionzero.voice")

# mot reconnu -> façon de le prononcer (pour les tests par voix de synthèse)
WORDS = {
    "iris": "iris",
    "clic": "clic",
    "double": "double",
    "menu": "menu",
    "glisse": "glisse",
    "lâche": "lâche",
    "défile": "défile",
    # « page » retiré : le geste (paume au bord) le fait déjà. La voix sert à ce que la main ne fait pas.
    "entrée": "entrée",
    "annule": "annule",   # touche Échap (« échap » n'existe pas dans le modèle)
    "copie": "copie",
    "colle": "colle",
    "claude": "Claude",   # « iris » puis « claude » : allume le micro de Claude dans VS Code
    "envoie": "envoie",   # après la dictée : envoie le message (Entrée)
    "pause": "pause",
    "retour": "retour",   # « iris retour » : revient à la fenêtre d'avant « iris claude »
    "tab": "tab",         # « iris tab » : comme Alt+Tab
    "discord": "Discord", # « iris discord » : Discord au premier plan (ou lancé)
    "chrome": "Chrome",   # « iris chrome » : Chrome au premier plan (ou lancé)
    "souris": "souris",   # « iris souris » : mode souris
    "mute": "mute",       # « iris mute » : coupe Discord
    "démute": "démute",   # « iris démute » : rallume Discord (entendu « des mute », absent du modèle)
    "stop": "stop",
}
WAKE_WORD = "iris"
LONE_MIN_CONF = 0.8
# « démute » n'existe pas dans le modèle : on l'écoute sous la forme « des mute », recollée ensuite
GRAMMAR = json.dumps([w for w in WORDS if w != "démute"] + ["des mute", "[unk]"], ensure_ascii=False)


def _join_demute(words):
    """« des » + « mute » entendus à la suite = la commande « démute »."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w["word"] == "des" and i + 1 < len(words) and words[i + 1]["word"] == "mute":
            nxt = words[i + 1]
            out.append({"word": "démute", "conf": min(w["conf"], nxt["conf"]), "start": w["start"], "end": nxt["end"]})
            i += 2
            continue
        out.append(w)
        i += 1
    return out


def accepted_words(res, min_conf=0.6, max_words=1):
    """Mots acceptés d'un résultat Vosk. Règle anti-faux-positifs : une commande doit être dite SEULE.
    Si la phrase contient un mot inconnu ([unk]) — conversation, série — ou plusieurs mots, TOUT est ignoré.
    Mesuré (voix de synthèse) : sans cette règle « il fait beau aujourd'hui » donnait « iris » (0,87) ;
    avec, 0 faux positif sur 12 phrases ordinaires."""
    words = _join_demute(res.get("result", []))
    # « euh », souffle, bruit juste avant « iris + commande » : toléré (mesuré : « [unk] iris claude » rejeté)
    if len(words) == 3 and words[0]["word"] == "[unk]" and words[1]["word"] == WAKE_WORD:
        words = words[1:]
    if not words or any(w["word"] == "[unk]" for w in words):
        return []
    # exception : « iris » + une commande dans la même phrase (« Iris, Claude » dit d'une traite)
    if len(words) == 2 and words[0]["word"] == WAKE_WORD and words[1]["word"] != WAKE_WORD:
        return words if all(w["conf"] >= min_conf for w in words) else []
    if len(words) > max_words:
        return []
    # un mot seul (sans « iris » dans la même phrase) doit être bien net : mesuré, « tab » à 0,60 et
    # « démute » à 0,81 étaient des faux déclenchements
    need = min_conf if words[0]["word"] == WAKE_WORD else max(min_conf, LONE_MIN_CONF)
    return [w for w in words if w["conf"] >= need]


FREE_MAX_WORDS = 4          # une commande est courte ; une phrase de conversation, non
ALWAYS_HEARD = {"stop", "lâche"}   # sécurité : jamais bloqués par la vérification


def confirmed(words, free_text):
    """2e vérification. La grammaire fermée « force » toute parole vers ses mots (mesuré : « tu as vu la
    série hier soir » -> « envoie », « une souris sans fil » -> « défile »). Une reconnaissance libre du même
    son doit donc confirmer : phrase courte, et « iris » vraiment prononcé s'il fait partie de la commande."""
    names = [w["word"] for w in words]
    if not names or set(names) & ALWAYS_HEARD:
        return True
    tokens = free_text.lower().split()
    if not tokens or len(tokens) > FREE_MAX_WORDS:
        return False
    if names[0] == WAKE_WORD:
        return any(tok.startswith("iri") for tok in tokens)
    return True


def rejection(res, min_conf=0.6):
    """Pourquoi un résultat contenant « iris » a été rejeté (pour le journal), ou None."""
    words = res.get("result", [])
    if not any(w["word"] == WAKE_WORD for w in words) or accepted_words(res, min_conf):
        return None
    return " ".join(f"{w['word']}({w['conf']:.2f})" for w in words)


@dataclass
class VoiceEvent:
    word: str
    conf: float
    t_start: float
    t_end: float


class VoiceListener:
    """Thread micro + reconnaissance. Les mots reconnus arrivent dans self.events (queue)."""

    def __init__(self, model_dir, min_conf=0.6, samplerate=16000):
        self.model_dir = model_dir
        self.min_conf = min_conf
        self.sr = samplerate
        self.events = queue.Queue()
        self.audio = queue.Queue(maxsize=200)
        self.running = False
        self.muted = False
        # « tu parles / tu te tais » au volume du micro (sert à couper la dictée Claude au bon moment)
        self.ambient = 200.0        # niveau du bruit de fond (RMS int16), appris pendant les moments calmes
        self._loud = 0.0
        self.thread = None
        self.stream = None
        self.t_stream0 = None
        self.last_speech_t = time.perf_counter()
        self.last_rms = 0.0         # pour le journal pendant la dictée
        self._partial = ""          # dernier texte provisoire de la reconnaissance

    def start(self):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.model = Model(self.model_dir)
        self.rec = KaldiRecognizer(self.model, self.sr, GRAMMAR)
        self.rec.SetWords(True)
        self.free = KaldiRecognizer(self.model, self.sr)   # sans grammaire : sert à vérifier (voir confirmed)
        self._free_final = (0.0, "")
        self.running = True
        self.t_stream0 = time.perf_counter()
        self.samples = 0
        # mode partagé (par défaut) : les autres applis peuvent utiliser le micro en même temps
        self.stream = sd.RawInputStream(samplerate=self.sr, blocksize=int(self.sr * 0.03), dtype="int16",
                                        channels=1, callback=self._callback)
        self.stream.start()
        self.thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self.thread.start()
        log.info("ecoute vocale demarree")
        return self

    def _callback(self, indata, frames, time_info, status):
        try:
            self.audio.put_nowait(bytes(indata))
        except queue.Full:
            pass  # on préfère perdre un bloc que bloquer l'audio

    def _run(self):
        while self.running:
            try:
                block = self.audio.get(timeout=0.2)
            except queue.Empty:
                continue
            start_samples = self.samples
            self.samples += len(block) // 2
            rms = _rms(block)
            self.last_rms = rms
            if rms < self.ambient * 1.5:  # seulement les moments calmes : la voix ne fausse pas le bruit de fond
                self.ambient = 0.98 * self.ambient + 0.02 * rms
            if rms >= min(max(self.ambient * 3.0, 400.0), 1500.0):
                self._loud += len(block) / 2 / self.sr
                if self._loud >= 0.15:  # un bruit bref ne compte pas comme de la parole
                    self.last_speech_t = time.perf_counter()
            else:
                self._loud = 0.0
            if self.muted:
                self.rec.Reset()
                self.free.Reset()
                continue
            now = time.perf_counter()
            if self.free.AcceptWaveform(block):
                self._free_final = (now, json.loads(self.free.Result()).get("text", ""))
            if self.rec.AcceptWaveform(block):
                self._partial = ""
                t_free, text = self._free_final
                if now - t_free > 1.5:   # la reconnaissance libre n'a pas encore fini sa phrase
                    text = json.loads(self.free.PartialResult()).get("partial", "")
                self._emit(json.loads(self.rec.Result()), text)
            else:
                # la reconnaissance entend un mot de plus (même inconnu) : c'est de la parole, quel que
                # soit le volume du micro (mesuré : VS Code le fait chuter à ~0-300 pendant sa dictée).
                # Seul un texte qui CHANGE compte : le dernier mot reste affiché un moment après la parole.
                partial = json.loads(self.rec.PartialResult()).get("partial", "").strip()
                if partial and partial != self._partial:
                    self.last_speech_t = time.perf_counter()
                self._partial = partial

    def _emit(self, res, free_text=None):
        why = rejection(res, self.min_conf)
        if why:
            log.info("iris rejete : %s", why)
        words = accepted_words(res, self.min_conf)
        if words and free_text is not None and not confirmed(words, free_text):
            log.info("non confirme : %s (entendu librement : '%s')", " ".join(w["word"] for w in words), free_text)
            return
        for w in words:
            ev =VoiceEvent(w["word"], w["conf"], self.t_stream0 + w["start"], self.t_stream0 + w["end"])
            log.info("voix %s (%.2f)", ev.word, ev.conf)
            self.events.put(ev)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def stop(self):
        self.running = False
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
        if self.thread is not None:
            self.thread.join(timeout=2.0)


def _rms(block):
    import numpy as np
    a = np.frombuffer(block, np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def default_model_dir(root):
    return os.path.join(root, "models", "vosk-model-small-fr-0.22")
