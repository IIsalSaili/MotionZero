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
    "tab": "tab",         # « iris tab » : comme Alt+Tab
    "discord": "Discord", # « iris discord » : Discord au premier plan (ou lancé)
    "chrome": "Chrome",   # « iris chrome » : Chrome au premier plan (ou lancé)
    "home": "home",       # « iris home » : la fenêtre d aperçu de motionzero, en plein écran
    "studio": "studio",   # « iris studio » : VS Code au premier plan, sans ouvrir le micro (« code » ressemble trop à « claude »)
    "souris": "souris",   # « iris souris » : mode souris
    "lecture": "lecture", # « iris lecture » : mode lecture (pages et défilement à la main)
    "question": "question",  # « iris question » : poser une question à Claude (réponse dans l'île)
    "ferme": "ferme",     # « iris ferme » : retirer la réponse affichée
    "mute": "mute",       # « iris mute » : coupe Discord
    "démute": "démute",   # « iris démute » : rallume Discord (entendu « des mute », absent du modèle)
    "défun": "défun",     # « iris défun / difun » : sourdine Discord, casque + micro (entendu « des fun » / « dis fun »)
    "stop": "stop",
}
WAKE_WORD = "iris"
END_SILENCE_S = 0.3   # délai entre la fin de la phrase et le résultat de la reconnaissance (environ)
LONE_MIN_CONF = 0.8
# « démute » n'existe pas dans le modèle : on l'écoute sous la forme « des mute », recollée ensuite
SPLIT = {("des", "mute"): "démute", ("un", "mute"): "démute",   # « unmute » = « démute », au choix
         ("des", "fun"): "défun", ("dis", "fun"): "défun"}
GRAMMAR = json.dumps([w for w in WORDS if w not in SPLIT.values()] + [f"{a} {b}" for a, b in SPLIT] + ["[unk]"],
                     ensure_ascii=False)


def _join_demute(words):
    """Mots absents du modèle, entendus en deux morceaux : « des mute » = démute, « des fun » / « dis fun » = défun."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        pair = (w["word"], words[i + 1]["word"]) if i + 1 < len(words) else None
        if pair in SPLIT:
            nxt = words[i + 1]
            out.append({"word": SPLIT[pair], "conf": min(w["conf"], nxt["conf"]), "start": w["start"], "end": nxt["end"]})
            i += 2
            continue
        out.append(w)
        i += 1
    return out


def accepted_words(res, min_conf=0.6, max_words=1):
    """Mots acceptés d'un résultat Vosk.
    - « iris » + une commande : pris n'importe où dans la phrase. Mesuré le 10/11 : avec de la parole en
      fond (vidéo, Discord), la reconnaissance colle « iris claude » au bruit d'avant (« stop pause stop iris
      claude ») et l'ancienne règle « dit seul » rejetait tout. La 2e vérification (confirmed) exige alors
      que « iris » ait vraiment été prononcé.
    - un mot sans « iris » : il doit être dit SEUL dans sa phrase, et net (sinon : conversation)."""
    words = _join_demute(res.get("result", []))
    if not words:
        return []
    for i in range(len(words) - 1, -1, -1):          # le dernier « iris » de la phrase
        if words[i]["word"] != WAKE_WORD or words[i]["conf"] < min_conf:
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            return [words[i]]                          # « iris » en fin de phrase : écoute ouverte
        if nxt["word"] not in ("[unk]", WAKE_WORD) and nxt["conf"] >= min_conf:
            return [words[i], nxt]
    if any(w["word"] == "[unk]" for w in words) or len(words) > max_words:
        return []
    # un mot seul (sans « iris » dans la même phrase) doit être bien net : mesuré, « tab » à 0,60 et
    # « démute » à 0,81 étaient des faux déclenchements
    need = min_conf if words[0]["word"] == WAKE_WORD else max(min_conf, LONE_MIN_CONF)
    return [w for w in words if w["conf"] >= need]


FREE_MAX_WORDS = 4          # un mot seul vient d'une phrase courte ; une phrase de conversation, non
ALWAYS_HEARD = {"stop", "lâche"}   # sécurité : jamais bloqués par la vérification


IRIS_SURE_CONF = 0.9        # « iris » entendu net par la grammaire, dans une phrase courte : pas de 2e avis
SHORT_PHRASE = 3            # « iris » + commande (+ un bruit au plus)


def confirmed(words, free_text, n_heard=None):
    """2e vérification. La grammaire fermée « force » toute parole vers ses mots (mesuré : « tu as vu la
    série hier soir » -> « envoie », « une souris sans fil » -> « défile »). Une reconnaissance libre du même
    son doit donc confirmer :
    - commande avec « iris » dite d'un trait (phrase courte, « iris » net) : acceptée telle quelle. Mesuré le
      10/11 : dit vite, la reconnaissance libre entend « la france » au lieu de « iris claude » ;
    - commande avec « iris » collée à d'autres paroles : « iris » vraiment prononcé ;
    - mot seul : phrase courte (mesuré : 8 mots de conversation bloqués en 30 min, ex. « d'accord » -> discord).
    n_heard : nombre de mots de la phrase entendue par la grammaire."""
    names = [w["word"] for w in words]
    if not names or set(names) & ALWAYS_HEARD:
        return True
    tokens = free_text.lower().split()
    if names[0] == WAKE_WORD:
        if n_heard is not None and n_heard <= SHORT_PHRASE and words[0].get("conf", 0) >= IRIS_SURE_CONF:
            return True
        return any(tok.startswith("iri") for tok in tokens)
    return 0 < len(tokens) <= FREE_MAX_WORDS


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
        self.last_rejected = None   # (texte affiché, instant) : commande entendue mais bloquée (pour l'île)
        self.capture = None         # morceaux de son gardés pendant « iris question »
        self.iris_heard_t = -1e9    # dernier « iris » repéré dans le texte PROVISOIRE (fige le curseur tôt)

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
        # une erreur sur un morceau de son ne doit jamais arrêter l'écoute (mesuré : une phrase vide
        # faisait planter le fil, et plus aucune commande vocale n'était entendue)
        while self.running:
            try:
                self._step()
            except Exception:
                log.exception("erreur dans l'ecoute vocale (on continue)")

    def _step(self):
        """Traite un morceau de son (30 ms)."""
        try:
            block = self.audio.get(timeout=0.2)
        except queue.Empty:
            return
        start_samples = self.samples
        self.samples += len(block) // 2
        if self.capture is not None:
            self.capture.append(block)
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
            return
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
                if WAKE_WORD in partial.split():
                    self.iris_heard_t = time.perf_counter()
            self._partial = partial

    def _emit(self, res, free_text=None):
        why = rejection(res, self.min_conf)
        if why:
            log.info("iris rejete : %s", why)
        words = accepted_words(res, self.min_conf)
        if not words:
            return
        if free_text is not None and not confirmed(words, free_text, len(res.get("result", []))):
            said = " ".join(w["word"] for w in words)
            log.info("non confirme : %s (entendu librement : '%s')", said, free_text)
            self.last_rejected = (f"« {said} » ignoré : pas sûr de l'avoir entendu", time.perf_counter())
            return
        # Dates sur l'horloge de l'appli, pas sur celle du flux audio : celle-ci dérive avec le temps et
        # repart de zéro quand l'écoute est mise en sourdine (dictée Claude). Mesuré : le clic vocal
        # ramenait alors le curseur à une position vieille de plusieurs secondes.
        # La phrase vient de finir (Vosk rend le résultat après un court silence) : on recale sur « maintenant ».
        now = time.perf_counter() - END_SILENCE_S
        last_end = max(w["end"] for w in words)
        for w in words:
            ev = VoiceEvent(w["word"], w["conf"], now - (last_end - w["start"]), now - (last_end - w["end"]))
            log.info("voix %s (%.2f)", ev.word, ev.conf)
            self.events.put(ev)

    def start_capture(self):
        self.capture = []

    def stop_capture(self):
        """Son enregistré depuis start_capture (int16, 16 kHz, mono)."""
        blocks, self.capture = self.capture or [], None
        return b"".join(blocks)

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
