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
from collections import deque
from dataclasses import dataclass

log = logging.getLogger("motionzero.voice")

# reconnaissance libre (2e avis) réveillée seulement par la parole : ~moitié moins de processeur au repos
FREE_WAKE_RATIO = 2.0     # volume au-dessus du bruit de fond qui la réveille
QUIET_WAKE_RATIO = 1.3    # voix basse (le soir) : réveillée par une voix plus faible (13/11 : « entendu librement : '' »)
QUIET_CHOICES = ("auto", "oui", "non")   # bouton de l'accueil ; auto = de QUIET_FROM_H à QUIET_TO_H
QUIET_FROM_H, QUIET_TO_H = 22, 7


def quiet_active(choice, hour, start=QUIET_FROM_H, end=QUIET_TO_H):
    """Voix basse en ce moment ? Pur : testable."""
    if choice == "oui":
        return True
    if choice == "non":
        return False
    return hour >= start or hour < end
FREE_TAIL_S = 2.0         # elle continue 2 s après le dernier son (le temps de finir sa phrase)
FREE_PREROLL_S = 1.0      # son gardé pendant son sommeil et rejoué au réveil
MAX_CAPTURE_S = 60.0      # enregistrement (question, type, ouvre) plafonné : jamais de mémoire sans fin

# mot reconnu -> façon de le prononcer (pour les tests par voix de synthèse)
WORDS = {
    "iris": "iris",
    "clic": "clic",
    "double": "double",
    "menu": "menu",
    "agrippe": "agrippe", # (15/11, remplace glisse / lâche) : enfonce le bouton, redit il le relâche
    "scroll": "scroll",   # « iris scroll » : défilement à la main / tête (ex-« défile », pris pour « défun » le 14/11)
    # « page » retiré : le geste (paume au bord) le fait déjà. La voix sert à ce que la main ne fait pas.
    "entrée": "entrée",
    # « espace » retiré le 19/11 (#50) : « iris space » seul
    "space": "space",
    "annule": "annule",   # touche Échap (« échap » n'existe pas dans le modèle)
    "copie": "copie",
    "colle": "colle",
    "sélection": "sélection",  # « iris sélection » : tout sélectionner (Ctrl+A)
    "coupe": "coupe",     # « iris coupe » : Ctrl+X
    "undo": "undo",       # « iris undo » : Ctrl+Z ; « iris redo » : Ctrl+Y (« redo » absent du modèle : « re do »)
    "redo": "redo",
    "efface": "efface",   # « iris efface » : efface le mot d'avant ; « efface, efface » sans « iris »
    "agrandis": "agrandis",  # « iris agrandis » : plein écran / « réduis » : fenêtre réduite (en mode Chrome : zoom)
    "plein écran": "plein écran",  # « iris plein écran » : plein écran partout, Chrome compris
    "réduis": "réduis",
    "gauche": "gauche",   # « iris gauche / droite » : fenêtre ancrée sur la moitié de l'écran
    "droite": "droite",
    "claude": "Claude",   # « iris » puis « claude » : allume le micro de Claude dans VS Code
    "envoie": "envoie",   # après la dictée : envoie le message (Entrée)
    "envoyé": "envoyé",   # synonyme d'« envoie » (même effet partout)
    "pause": "pause",
    "aide": "aide",       # « iris aide » : toutes les commandes, celles du mode en cours en tête
    "guide": "guide",     # « iris guide » : la documentation sur GitHub
    "reprise": "reprise", # « iris reprise » : sort de la pause (« iris » seul ne suffit plus)
    "tab": "tab",         # « iris tab » : comme Alt+Tab
    "discord": "Discord", # « iris discord » : Discord au premier plan (ou lancé)
    "chrome": "Chrome",   # « iris chrome » : Chrome au premier plan (ou lancé)
    "accueil": "accueil", # « iris accueil » (« home » se confondait avec « chrome ») : la fenêtre d aperçu de motionzero au premier plan
    "studio": "studio",   # « iris studio » : VS Code au premier plan, sans ouvrir le micro (« code » ressemble trop à « claude »)
    "souris": "souris",   # « iris souris » : mode souris
    "lecture": "lecture", # « iris lecture » : mode lecture (pages et défilement à la main)
    "type": "type",       # « iris type » : dicter du texte, écrit là où se trouve le curseur
    "question": "question",  # « iris question » : poser une question à Claude (réponse dans l'île)
    "ferme": "ferme",     # « iris ferme » : retirer la réponse affichée
    "mute": "mute",       # « iris mute » : coupe Discord
    "sourdine": "sourdine",  # « iris sourdine » : sourdine Discord, casque + micro
    "tête": "tête",       # « iris tête » / « iris main » : ce qui pilote la souris
    "main": "main",
    "centre": "centre",   # « iris centre » : curseur au centre, tête de face = nouvelle référence
    # « activation » et « favori » retirés le 19/11 (#50) : « viens » suffit, le bot est relancé seul
    "démute": "démute",   # « iris démute » : rallume Discord (entendu « des mute », absent du modèle)
    "silence": "silence", # « iris silence » : coupe la lecture à voix haute des messages Discord
    "lis": "lis",         # « iris lis » : la remet
    "skip": "skip",       # « iris skip » : flèche droite (YouTube : +10 s)
    "back": "back",       # « iris back » : flèche gauche (YouTube : -10 s)
    "merci": "merci",     # « iris merci » : retire ce qui est affiché en haut (rappel, réponse…) ; « ok » retiré le 14/11
    "plus tard": "plus tard",  # « iris plus tard » : le rappel revient dans 10 min
    "réveil": "réveil",   # « iris réveil » : rallume l'écran éteint (« wake » retiré le 14/11 : jamais utilisé)
    "calendrier": "calendrier",   # « iris calendrier » : la semaine en 7 cartes (#21)
    "heure": "heure",     # « iris heure » / « iris date » : jour, date et heure affichés quelques secondes
    "date": "date",
    "focus": "focus",     # « iris focus » : plus besoin de dire « iris » ; « focus » seul l'éteint
    "quota": "quota",     # « iris quota » : affiche / masque le quota Claude (session de 5 h) en haut à droite
    "viens": "viens",     # « iris viens » : le bot vocal rejoint ton salon et répond quand on dit « Iris » (bot #1)
    "pars": "pars",       # « iris pars » : il quitte le vocal
    "traducteur": "traducteur",   # « iris traducteur » : sous-titres traduits du son du PC ; redit, éteint
    "instruction": "instruction",
    "bypass": "bypass",           # « iris bypass » : mots acceptés même mal dits (sauf les définitifs) ; redit, éteint  # « iris instruction » puis une demande libre : plan affiché, « envoie » le fait
    "candidature": "candidature",   # « iris candidature » : Iris pilote CVGEN (plan-cvgen.md) ; redit, éteint
    "stop": "stop",
}

# Passées dans « iris instruction » (17/11, choix de l'utilisateur) : plus guettées par Vosk (moins de fausses
# détections). Toujours comprises en MP Discord et par Core.
VIA_INSTRUCTION = {"ouvre", "message", "rappel", "chronomètre", "timer", "volume", "salon"}


WAKE_WORD = "iris"
END_SILENCE_S = 0.3   # délai entre la fin de la phrase et le résultat de la reconnaissance (environ)
LONE_MIN_CONF = 0.8
# « iris » puis la commande, d'un trait : 14/11, « iris m'a mis en sourdine » (dit dans la conversation, voix basse)
# a été entendu « iris sourdine » et a mis la sourdine. Au-delà de ce blanc, ce n'est pas une commande.
IRIS_GAP_S = 0.35
# « démute » n'existe pas dans le modèle : on l'écoute sous la forme « des mute », recollée ensuite
SPLIT = {("des", "mute"): "démute",   # « un mute » retiré le 14/11 : « un » seul était pris dans la conversation
         ("plus", "tard"): "plus tard",
         ("re", "do"): "redo",
         ("plein", "écran"): "plein écran",
         ("double", "clic"): "double"}
# mots en deux morceaux des modes (candidature, Chrome) : recollés, mais jamais ajoutés aux grammaires de base
MODE_SPLIT = {("code", "postal"): "code postal", ("prépare", "tout"): "prépare tout",
              ("dé", "zoom"): "dézoom"}   # « dézoom » absent du modèle : « dé zoom », mode Chrome seulement
SPOKEN = {v: f"{a} {b}" for (a, b), v in MODE_SPLIT.items()}   # mot de mode -> ce que Vosk doit chercher   # « double clic » dit en entier = « double » (2 mots : rejeté avant)
SOLO_TOO = {"double"}                     # aussi écouté seul (contrairement à « démute », absent du modèle)
CAL_ONLY = set()   # mots du calendrier (jours, mois, nombres) : écoutés seulement calendrier ouvert


# mots de la souris : écoutés seulement souris allumée (ou bouton tenu) et en mode Chrome (14/11 : partout,
# ils étaient pris dans la conversation : clic 60 fois, menu 38, glisse 23)
MOUSE_ONLY = {"clic", "double", "menu", "agrippe"}   # « scroll » écouté partout (sans souris)


def grammar(extra=(), mouse=True):
    skip = CAL_ONLY | (set() if mouse else MOUSE_ONLY)
    phrases = [w for w in WORDS if (w not in SPLIT.values() or w in SOLO_TOO) and w not in skip]
    phrases += [f"{a} {b}" for a, b in SPLIT if mouse or SPLIT[(a, b)] not in MOUSE_ONLY]
    if not mouse:   # souris éteinte : seulement précédés de « iris » (16/11 : « iris clic » devenait « iris lis »)
        phrases += [f"iris {w}" for w in sorted(MOUSE_ONLY)] + ["iris double clic"]
    phrases += [SPOKEN.get(w, w) for w in extra if SPOKEN.get(w, w) not in phrases]
    return json.dumps(phrases + ["[unk]"], ensure_ascii=False)


def _calendar_words():
    """Jours, nombres, suivant / précédent : ne servent que calendrier ouvert (voir core.voice)."""
    from .calendar_view import WORDS as CAL
    for w in CAL:
        WORDS.setdefault(w, w)
    # 14/11 : les 45 mots du calendrier toujours écoutés gênaient « iris » (pris pour « août », « mai »…) ;
    # seuls « suivant / précédent » restent partout (onglets de VS Code)
    CAL_ONLY.update(w for w in CAL if w not in ("suivant", "précédent"))


_calendar_words()
GRAMMAR = grammar(mouse=False)


def _grammars():
    """Une liste de mots par mode : les mots de Chrome (« haut », « bas »…) ne sont même pas cherchés ailleurs,
    pour ne pas prendre un mot de la conversation pour une commande (demande de l'utilisateur, 12/11)."""
    from .calendar_view import WORDS as CAL
    from .core import CHROME_KEYS
    return {"base": GRAMMAR, "souris": grammar(), "chrome": grammar(CHROME_KEYS),
            "calendrier": grammar(CAL, mouse=False),
            "candidature": cand_grammar(False), "candidature_souris": cand_grammar(True)}


def cand_grammar(mouse):
    """« iris candidature » (17/11, demande de l'utilisateur) : SEULS ses mots, plus « stop » (toujours) et
    « souris » ; les mots de la souris seulement souris allumée. Aucun autre mot de base, ni ceux de Chrome."""
    from .cvgen import WORDS as CAND
    phrases = list(CAND) + ["candidature", "stop", "souris"]
    if mouse:
        phrases += sorted(MOUSE_ONLY) + ["double clic", "scroll"]
    return json.dumps(phrases + ["[unk]"], ensure_ascii=False)


GRAMMARS = _grammars()


def _join_demute(words):
    """Mots absents du modèle, entendus en deux morceaux : « des mute » = démute."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        pair = (w["word"], words[i + 1]["word"]) if i + 1 < len(words) else None
        if pair in SPLIT or pair in MODE_SPLIT:
            nxt = words[i + 1]
            out.append({"word": SPLIT.get(pair) or MODE_SPLIT[pair], "conf": min(w["conf"], nxt["conf"]), "start": w["start"], "end": nxt["end"]})
            i += 2
            continue
        out.append(w)
        i += 1
    return out


# « iris » suivi d'une commande nette : seuil bas. Mesuré du 11 au 15/11 : 10 à 27 rejets par jour du type
# « iris(0.37) claude(1.00) » ; dire « iris » puis une commande par hasard est rare, et la 2e vérification reste.
IRIS_MIN_CONF = 0.3

# « iris bypass » (17/11) : quand l'utilisateur sait qu'il ne parlera pas à côté. Seuils plus bas et pas de 2e
# vérification, sauf pour les mots qui font une action définitive (fermer, envoyer, effacer…).
BYPASS_MIN_CONF = 0.4       # commande après « iris » (normal : 0,6)
BYPASS_LONE_CONF = 0.55     # mot dit seul, en focus (normal : 0,8)
BYPASS_EXCLUDED = {"ferme", "envoie", "envoyé", "annule", "efface", "coupe", "recharge", "stop", "agrippe",
                   "instruction", "bypass"}


def bypassable(word, bypass):
    return bool(bypass) and word not in BYPASS_EXCLUDED and word != WAKE_WORD


def accepted_words(res, min_conf=0.6, max_words=1, relaxed=frozenset(), bypass=False):
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
        if words[i]["word"] != WAKE_WORD or words[i]["conf"] < min(min_conf, IRIS_MIN_CONF):
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            if words[i]["conf"] < min_conf:
                continue                               # « iris » seul : seuil normal
            return [words[i]]                          # « iris » en fin de phrase : écoute ouverte
        need_next = BYPASS_MIN_CONF if bypassable(nxt["word"], bypass) else min_conf
        if nxt["word"] not in ("[unk]", WAKE_WORD) and nxt["conf"] >= need_next:
            if _gap(words[i], nxt) > IRIS_GAP_S:
                return []                              # « iris m'a mis en sourdine » : des mots au milieu
            return [words[i], nxt]
    if any(w["word"] == "[unk]" for w in words) or len(words) > max_words:
        return []
    # un mot seul (sans « iris » dans la même phrase) doit être bien net : mesuré, « tab » à 0,60 et
    # « démute » à 0,81 étaient des faux déclenchements
    # relaxed : mots attendus à ce moment précis (« envoie / annule » juste après une dictée) : seuil normal
    lone = words[0]["word"] != WAKE_WORD and words[0]["word"] not in relaxed
    need = max(min_conf, LONE_MIN_CONF) if lone else min_conf
    if bypassable(words[0]["word"], bypass):
        need = BYPASS_LONE_CONF if lone else min(need, BYPASS_MIN_CONF)
    return [w for w in words if w["conf"] >= need]


def _gap(a, b):
    """Blanc entre deux mots de la grammaire (s). La grammaire fermée avale les mots qu'elle ne connaît pas : un
    long blanc entre « iris » et la commande, c'est qu'on a dit autre chose au milieu."""
    try:
        return max(0.0, float(b["start"]) - float(a["end"]))
    except (KeyError, TypeError, ValueError):
        return 0.0


FREE_MAX_WORDS = 4          # un mot seul vient d'une phrase courte ; une phrase de conversation, non
ALWAYS_HEARD = {"stop", "agrippe", "candidature"}   # jamais bloqués par la vérification (candidature : demandé le 22/11, même dans une phrase)


QUIET_IRIS_CONF = 0.7       # voix basse : « iris » moins net, accepté plus tôt
IRIS_SURE_CONF = 0.9        # « iris » entendu net par la grammaire, dans une phrase courte : pas de 2e avis
AFTER_IRIS_S = 4.0          # mot dit seul juste après un « iris » accepté : c'est la commande attendue
SHORT_PHRASE = 3            # « iris » + commande (+ un bruit au plus)


def _dedupe(tokens):
    """« skype skype skype » -> « skype » : un mot redit vite (« skip skip skip ») n'est pas une phrase."""
    return [tok for i, tok in enumerate(tokens) if i == 0 or tok != tokens[i - 1]]


def confirmed(words, free_text, n_heard=None, after_iris=False, quiet=False, relaxed=frozenset(), bypass=False):
    """2e vérification. La grammaire fermée « force » toute parole vers ses mots (mesuré : « tu as vu la
    série hier soir » -> « envoie », « une souris sans fil » -> « défile »). Une reconnaissance libre du même
    son doit donc confirmer :
    - commande avec « iris » dite d'un trait (phrase courte, « iris » net) : acceptée telle quelle. Mesuré le
      10/11 : dit vite, la reconnaissance libre entend « la france » au lieu de « iris claude » ;
    - commande avec « iris » collée à d'autres paroles : « iris » vraiment prononcé ;
    - mot seul : phrase courte (mesuré : 8 mots de conversation bloqués en 30 min, ex. « d'accord » -> discord).
    n_heard : nombre de mots de la phrase entendue par la grammaire.
    after_iris : un « iris » vient d'être accepté. Le mot suivant est accepté sans 2e vérification : avec du
    bruit autour, la reconnaissance libre colle tout en une longue phrase (mesuré le 13/11 : « iris » puis
    « pause » refusé 5 fois de suite, « ...les couilles pose l s »). Il n'agit de toute façon qu'après « iris ».
    quiet : voix basse (le soir). Parlé doucement, la reconnaissance libre n'entend rien (texte vide) ou
    déforme « iris » (« cerise claude », 13/11) : un texte vide confirme un mot seul, « iris » moins net suffit,
    et un mot finissant par « ris », « rise » ou « rice » (cerise, Maurice) compte pour « iris ». Les phrases longues restent refusées."""
    names = [w["word"] for w in words]
    if not names or set(names) & ALWAYS_HEARD:
        return True
    cmds = [n for n in names if n != WAKE_WORD]
    if cmds and all(bypassable(n, bypass) for n in cmds):
        return True                   # bypass : pas de 2e vérification (les mots définitifs l'ont toujours)
    if after_iris and names[0] != WAKE_WORD and len(names) == 1:
        return True
    tokens = _dedupe(free_text.lower().split())
    if len(names) == 1 and names[0] in relaxed and len(tokens) <= FREE_MAX_WORDS:
        return True                   # attendu (après une dictée) : un texte libre vide confirme aussi (14/11)
    if names[0] == WAKE_WORD:
        sure = QUIET_IRIS_CONF if quiet else IRIS_SURE_CONF
        if n_heard is not None and n_heard <= SHORT_PHRASE and words[0].get("conf", 0) >= sure:
            return True
        return any(tok.startswith("iri") or (quiet and tok.endswith(("ris", "rise", "rice"))) for tok in tokens)
    return (0 if quiet else 1) <= len(tokens) <= FREE_MAX_WORDS


def rejection(res, min_conf=0.6):
    """Pourquoi un résultat contenant « iris » a été rejeté (pour le journal), ou None."""
    words = res.get("result", [])
    if not any(w["word"] == WAKE_WORD for w in words) or accepted_words(res, min_conf):
        return None
    return " ".join(f"{w['word']}({w['conf']:.2f})" + (f" [blanc {_gap(w, n):.2f} s]" if w["word"] == WAKE_WORD
                    and _gap(w, n) > IRIS_GAP_S else "") for w, n in zip(words, words[1:] + [words[-1]]))


def apercu(text, n=4):
    """Les n premiers mots seulement (#49) : le journal ne garde pas les conversations privées."""
    words = (text or "").split()
    if len(words) <= n:
        return "'%s'" % " ".join(words)
    return "'%s…' (%d mots)" % (" ".join(words[:n]), len(words))


@dataclass
class VoiceEvent:
    word: str
    conf: float
    t_start: float
    t_end: float


STALL_S = 3.0        # plus aucun morceau de son (même silencieux) depuis 3 s : le flux du micro est figé
STALL_RETRY_S = 10.0 # entre deux réouvertures, si le micro reste muet (débranché…)


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
        self.quiet = False          # voix basse : écrit par la boucle principale (un booléen), lu ici
        self.conversation = True    # bouton « mode conversation » de l'accueil : décoché, pas de 2e vérification
        self.bypass = False         # « iris bypass » : écrit par la boucle principale (un booléen), lu ici
        self.relaxed = frozenset()  # mots attendus maintenant (« envoie / annule » après une dictée) : idem
        self._iris_ok_t = -1e9      # dernier « iris » accepté (le mot qui suit n'est pas re-vérifié)
        self.iris_heard_t = -1e9    # dernier « iris » repéré dans le texte PROVISOIRE (fige le curseur tôt)
        self.last_block_t = -1e9    # dernier morceau de son reçu du micro (même silencieux)
        self._stall_try_t = -1e9    # dernière réouverture automatique (micro figé)
        # liste de mots voulue (« base » / « chrome ») : écrite par la boucle, appliquée par le fil voix
        self.grammar = "base"
        self._grammar = "base"

    def start(self):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.model = Model(self.model_dir)
        self.rec = KaldiRecognizer(self.model, self.sr, GRAMMAR)
        self.rec.SetWords(True)
        self.free = KaldiRecognizer(self.model, self.sr)   # sans grammaire : sert à vérifier (voir confirmed)
        self._free_final = (0.0, "")
        self._free_pre = deque(maxlen=int(FREE_PREROLL_S / 0.03))
        self._free_until = 0.0
        self._was_muted = False
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
        self.last_block_t = time.perf_counter()
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
            self.check_stalled()
            return
        start_samples = self.samples
        self.samples += len(block) // 2
        capture = self.capture   # lu une seule fois : stop_capture (autre fil) peut le remettre à None
        if capture is not None and len(capture) < MAX_CAPTURE_S / 0.03:
            capture.append(block)
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
            if not self._was_muted:          # une seule remise à zéro, pas une à chaque morceau
                self.rec.Reset()
                self.free.Reset()
                self._free_pre.clear()
                self._was_muted = True
            return
        self._was_muted = False
        want = self.grammar
        if want != self._grammar and want in GRAMMARS:
            self.rec.Reset()                      # Vosk refuse de changer la liste en pleine phrase
            self.rec.SetGrammar(GRAMMARS[want])   # entre deux morceaux de son, dans ce fil uniquement
            self._grammar = want
            log.info("liste de mots : %s", want)
        now = time.perf_counter()
        # Reconnaissance libre (la plus chère) : seulement quand quelqu'un parle. Le reste du temps, le
        # son est gardé ~1 s et lui est redonné au réveil, pour ne pas perdre le début de la phrase.
        if rms >= self.ambient * (QUIET_WAKE_RATIO if self.quiet else FREE_WAKE_RATIO) or self._partial:
            self._free_until = now + FREE_TAIL_S
        if now < self._free_until:
            for old in self._free_pre:
                self.free.AcceptWaveform(old)
            self._free_pre.clear()
            if self.free.AcceptWaveform(block):
                self._free_final = (now, json.loads(self.free.Result()).get("text", ""))
        else:
            self._free_pre.append(block)
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
        relaxed = getattr(self, "relaxed", frozenset())   # (écouteurs de test créés sans __init__)
        bypass = getattr(self, "bypass", False)
        words = accepted_words(res, self.min_conf, relaxed=relaxed, bypass=bypass)
        if not words:
            return
        after_iris = time.perf_counter() - self._iris_ok_t < AFTER_IRIS_S
        if free_text is not None and getattr(self, "conversation", True) and not confirmed(words, free_text, len(res.get("result", [])), after_iris,
                                                   self.quiet, relaxed, bypass):
            said = " ".join(w["word"] for w in words)
            log.info("non confirme : %s (entendu librement : %s)", said, apercu(free_text))
            self.last_rejected = (f"« {said} » ignoré : pas sûr de l'avoir entendu", time.perf_counter())
            return
        # Dates sur l'horloge de l'appli, pas sur celle du flux audio : celle-ci dérive avec le temps et
        # repart de zéro quand l'écoute est mise en sourdine (dictée Claude). Mesuré : le clic vocal
        # ramenait alors le curseur à une position vieille de plusieurs secondes.
        # La phrase vient de finir (Vosk rend le résultat après un court silence) : on recale sur « maintenant ».
        now = time.perf_counter() - END_SILENCE_S
        last_end = max(w["end"] for w in words)
        # mesure de la lenteur (14/11) : attente du silence par Vosk, et son en retard dans la file
        stream_t = getattr(self, "samples", 0) / self.sr if getattr(self, "sr", 0) else 0.0
        audio = getattr(self, "audio", None)
        log.info("delai : fin du mot -> resultat %.2f s, file %.2f s",
                 max(0.0, stream_t - last_end), (audio.qsize() * 0.03) if audio is not None else 0.0)
        for w in words:
            ev = VoiceEvent(w["word"], w["conf"], now - (last_end - w["start"]), now - (last_end - w["end"]))
            if w["word"] == WAKE_WORD:
                self._iris_ok_t = time.perf_counter()
            self.events.put(ev)   # noté au journal par la boucle (avec « acceptée / ignorée »)

    def reopen(self):
        """Rouvre le micro (après « réparer le son ») : l'ancien flux est abandonné sans l'attendre (il peut
        être figé), PortAudio relit la liste des micros, puis un nouveau flux s'ouvre sur le micro par défaut."""
        import sounddevice as sd
        old, self.stream = self.stream, None
        if old is not None:
            def close():
                try:
                    old.abort()
                    old.close()
                except Exception:
                    pass
            t = threading.Thread(target=close, name="ferme-micro", daemon=True)
            t.start()
            t.join(3.0)
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            log.exception("reinitialisation de l'audio")
        finally:
            after = getattr(self, "after_reopen", None)
            if after is not None:
                after()                   # la sortie des sons d'Iris est morte avec PortAudio : à rouvrir
        self.stream = sd.RawInputStream(samplerate=self.sr, blocksize=int(self.sr * 0.03), dtype="int16",
                                        channels=1, callback=self._callback)
        self.stream.start()
        log.info("micro rouvert : %s", sd.query_devices(kind="input")["name"])

    def check_stalled(self, now=None):
        """Micro figé (14/11 : plus aucun son reçu, Iris sourde jusqu'à sa relance) : rouvre le flux tout seul.
        Un casque muté par son bouton envoie encore du silence : ça ne compte pas comme figé."""
        if self.stream is None or self.t_stream0 is None:
            return False
        now = time.perf_counter() if now is None else now
        last = max(self.last_block_t, self.t_stream0)
        if now - last < STALL_S or now - self._stall_try_t < STALL_RETRY_S:
            return False
        self._stall_try_t = now
        log.warning("micro fige (aucun son depuis %.1f s) : flux rouvert", now - last)
        try:
            self.reopen()
        except Exception:
            log.exception("reouverture du micro fige")
        return True

    def heard_since(self, t):
        return self.last_block_t > t

    def start_capture(self):
        self.capture = []

    def stop_capture(self):
        """Son enregistré depuis start_capture (int16, 16 kHz, mono) ; ou le texte d'un MP Discord (#43),
        déposé dans `typed` par la boucle principale : il remplace l'enregistrement, Whisper est sauté."""
        typed, self.typed = getattr(self, "typed", None), None
        if typed is not None:
            self.capture = None
            return typed
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
