"""Commandes vocales hors ligne (Vosk, petit modèle français, grammaire fermée) : constantes et fonctions (1/1, découpé de voice.py, #52)."""
import json
import logging
import os
from dataclasses import dataclass

from .alttab import ALTTAB_NUMBERS

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
    "alt-tab": "alt tab", # « iris alt-tab » : fenêtre d'avant, puis « deux »… : liste en haut (#75)
    "discord": "Discord", # « iris discord » : Discord au premier plan (ou lancé)
    "chrome": "Chrome",   # « iris chrome » : Chrome au premier plan (ou lancé)
    "accueil": "accueil", # « iris accueil » (« home » se confondait avec « chrome ») : la fenêtre d aperçu de motionzero au premier plan
    "studio": "studio",   # « iris studio » : VS Code au premier plan, sans ouvrir le micro (« code » ressemble trop à « claude »)
    "souris": "souris",   # « iris souris » : mode souris
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
         ("double", "clic"): "double",
         ("alt", "tab"): "alt-tab"}
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
    phrases += [f"alt tab {n}" for n in ALTTAB_NUMBERS]   # « iris alt-tab trois » d'un trait
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
    nums = list(ALTTAB_NUMBERS)   # liste d'« alt-tab » affichée : ses chiffres, en plus des mots du moment
    return {"base": GRAMMAR, "souris": grammar(), "chrome": grammar(CHROME_KEYS),
            "alttab": grammar(nums, mouse=False), "alttab_souris": grammar(nums),
            "alttab_chrome": grammar(list(CHROME_KEYS) + nums),
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
            num = words[i + 2] if i + 2 < len(words) else None
            if (nxt["word"] == "alt-tab" and num and num["word"] in ALTTAB_NUMBERS and num["conf"] >= min_conf
                    and _gap(nxt, num) <= IRIS_GAP_S):  # « iris alt-tab trois » : un seul mot, « alt-tab trois »
                return [words[i], dict(nxt, word=f"alt-tab {num['word']}", conf=min(nxt["conf"], num["conf"]),
                                       end=num["end"])]
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


def _rms(block):
    import numpy as np
    a = np.frombuffer(block, np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def default_model_dir(root):
    return os.path.join(root, "models", "vosk-model-small-fr-0.22")
