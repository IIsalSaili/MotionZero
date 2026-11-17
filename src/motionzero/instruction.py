"""« iris instruction » (#45) : une phrase libre -> Whisper -> modèle local (Ollama) -> plan d'actions d'Iris.

Le modèle ne fait rien lui-même : il choisit dans un catalogue FERMÉ d'outils écrits ici. Le plan est vérifié
(outil connu, argument valide), affiché en haut de l'écran, et exécuté seulement après « envoie ».
« annule » l'abandonne ; « stop » arrête un plan en cours entre deux étapes.

Fils : la transcription et le modèle tournent dans le fil « instruction », l'exécution dans « instruction-exec ».
Ils ne rendent compte que par la queue `_q`, lue par events() dans la boucle principale (jamais Core ailleurs).
"""
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("motionzero.instruction")

MODEL = "qwen3:4b"
OLLAMA = "http://127.0.0.1:11434"
KEEP_ALIVE = "5m"          # modèle déchargé de la carte graphique après 5 min sans instruction
LLM_TIMEOUT_S = 60
HELP_S = 25.0              # la carte d'exemples reste ce temps
HELP_HINT = "Pour des exemples : « iris instruction », puis « aide »."
CLOSE_HINT = "« iris merci » pour fermer"
HELP_WORDS = ("aide", "exemple", "sais faire", "tu sais faire", "peux faire", "comment ca marche", "quoi dire")


def is_help(phrase):
    from .outils import norm_name
    p = norm_name(phrase)
    return any(w in p for w in HELP_WORDS) and len(p) < 60


# Faits sans « envoie » quand le plan ne contient qu'eux (choix de l'utilisateur, 17/11) : les commandes qui
# existaient seules avant (ouvre, timer, rappel, volume, message, salon, chronomètre). Tout autre outil dans le
# plan : « envoie » obligatoire pour l'ensemble.
DIRECT = {"ouvre_app", "site", "timer", "rappel", "volume", "discord_message", "discord_salon", "chronometre"}
CONFIRM_S = 10.0          # sans « envoie » dans ce temps : plan annulé (jamais lancé seul)
MAX_STEPS = 8
STEP_PAUSE_S = 0.8         # entre deux étapes : la fenêtre ouverte a le temps de passer devant
SHOW_DONE_S = 8.0          # le compte rendu reste affiché ce temps
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0 Safari/537.36")

KEY_NAMES = {"entree": "enter", "entrée": "enter", "echap": "escape", "échap": "escape", "espace": "space",
             "tab": "tab", "haut": "up", "bas": "down", "gauche": "left", "droite": "right",
             "retour": "backspace", "ctrl": "ctrl", "alt": "alt", "maj": "shift", "shift": "shift", "win": "win"}

# outil -> description pour le modèle. L'argument est toujours une chaîne (vide si inutile).
TOOLS = {
    "ouvre_app": "ouvre une application installée (arg : son nom, ex. « chrome », « discord », « word »)",
    "ferme_app": "ferme une application (arg : son nom)",
    "site": "ouvre un site par son nom ou son adresse (arg : ex. « mes mails », « leboncoin », « youtube.com »)",
    "recherche_web": "ouvre une recherche Google dans le navigateur (arg : les mots cherchés)",
    "youtube": "ouvre directement la 1re vidéo YouTube trouvée pour une recherche (arg : la recherche)",
    "youtube_chaine": "ouvre directement la dernière vidéo publiée par une chaîne YouTube (arg : le nom de la chaîne)",
    "touche": "appuie sur une touche ou un raccourci (arg : ex. « entrée », « ctrl+t », « alt+tab », « f5 »)",
    "ecris": "écrit un texte là où se trouve le curseur (arg : le texte)",
    "volume": "règle le son du PC (arg : « 40 », « plus fort », « moins fort », « coupe », « remets »)",
    "discord": "micro Discord (arg : « coupe », « allume » ou « sourdine »)",
    "discord_salon": "te déplace dans un salon vocal Discord (arg : le nom du salon)",
    "discord_message": "envoie un message Discord par le bot (arg : « dans <salon ou personne>, <le message> »)",
    "timer": "lance un compte à rebours (arg : la durée, ex. « 5 minutes »)",
    "rappel": "crée un rappel, à valider ensuite (arg : la demande, ex. « demain 9 h appeler le médecin »)",
    "traducteur": "allume ou éteint les sous-titres traduits du son du PC (arg vide)",
    "chronometre": "démarre le chronomètre, ou l'arrête s'il tourne (arg vide)",
    "attends": "attend quelques secondes (arg : nombre de secondes, 10 au plus)",
    # routines : une suite d'étapes enregistrée sous un nom, rejouée ensuite
    "routine": "lance une routine enregistrée (arg : son nom, parmi les routines connues)",
    "cree_routine": "enregistre les AUTRES étapes du plan sous un nom au lieu de les faire (arg : le nom)",
    "oublie_routine": "oublie une routine (arg : son nom)",
    "refais": "refait la dernière instruction réussie (arg vide)",
    "aide": "montre des exemples de demandes (arg vide) : pour « aide », « qu'est-ce que tu sais faire »",
    # navigateur
    "recherche": "ouvre la page de résultats d'un site (arg : « site: texte » ; sites : google, youtube, amazon, "
                 "maps, itineraire, wikipedia, twitch, spotify, images)",
    "historique": "rouvre la page la plus récente de l'historique de Chrome qui correspond (arg : quelques mots)",
    "historique_video": "rouvre la vidéo YouTube la plus récente de l'historique qui correspond (arg : quelques mots)",
    "onglet": "passe à l'onglet de Chrome dont le titre contient ces mots (arg : les mots)",
    "ferme_onglets": "ferme les onglets de Chrome dont le titre contient ces mots (arg : les mots)",
    "rouvre_onglet": "rouvre le dernier onglet fermé (arg vide)",
    "video": "commande la vidéo YouTube devant (arg : pause, lecture, plein écran, avance, recule, suivante, "
             "sous-titres, muet, début)",
    # musique (touches multimédia : Spotify, YouTube…)
    "musique": "lecture / pause / suivant / précédent de la musique en cours (arg : l'un de ces mots)",
    # fenêtres
    "devant": "met une application ouverte au premier plan (arg : son nom)",
    "fenetre": "place une application (arg : « nom: gauche », « nom: droite » ou « nom: plein »)",
    # infos affichées, rien n'est modifié
    "meteo": "affiche la météo (arg : la ville)",
    "heure_ville": "affiche l'heure dans une ville (arg : la ville)",
    "calcul": "affiche le résultat d'un calcul (arg : le calcul, ex. « 15 % de 240 »)",
    "conversion": "affiche une conversion d'unités ou de devises (arg : ex. « 5 miles en km », « 20 euros en dollars »)",
    "agenda": "affiche les rappels à venir (arg vide)",
}
EXPANDING = {"routine", "refais"}       # remplacés par leurs étapes au moment du plan

SYSTEM = (
    "Tu transformes une demande orale (transcrite, donc parfois approximative) en plan d'actions pour Iris, "
    "l'assistant d'un utilisateur qui ne peut pas se servir de ses mains. Tu ne peux utiliser QUE ces outils :\n"
    + "\n".join(f"- {k} : {v}" for k, v in TOOLS.items()) +
    "\nRègles :\n"
    "- Pour une vidéo YouTube, utilise youtube ou youtube_chaine directement (ils ouvrent eux-mêmes le navigateur) : "
    "jamais ouvrir Chrome puis taper dans la barre.\n"
    "- Pour une vidéo déjà vue, utilise historique_video ; pour ouvrir un site, site avec son nom.\n"
    "- « crée la routine X : … » -> cree_routine X puis les étapes de la routine.\n"
    "- Le moins d'étapes possible, " + str(MAX_STEPS) + " au plus.\n"
    "- Si la demande est impossible avec ces outils, ou dangereuse, ou incompréhensible : étapes vides et "
    "explique en une courte phrase dans « refus ».\n"
    "- Interdit, même en combinant des outils : supprimer, déplacer ou modifier des fichiers, taper des commandes "
    "(terminal, invite de commandes, PowerShell, explorateur), payer, changer des réglages. "
    "Pour ces demandes : étapes vides et refus.\n"
    "- Chaque étape doit servir directement la demande : jamais d'étape de remplacement quand le vrai but est "
    "impossible.\n"
    "Exemples :\n"
    "« crée la routine mode travail : ouvre Discord et mets le son à 30 » -> {\"etapes\": [{\"outil\": \"cree_routine\", "
    "\"arg\": \"mode travail\"}, {\"outil\": \"ouvre_app\", \"arg\": \"discord\"}, {\"outil\": \"volume\", \"arg\": \"30\"}], "
    "\"refus\": \"\"}\n"
    "« va sur l'onglet Gmail » -> {\"etapes\": [{\"outil\": \"onglet\", \"arg\": \"Gmail\"}], \"refus\": \"\"}\n"
    "« cherche un casque sur Amazon » -> {\"etapes\": [{\"outil\": \"recherche\", \"arg\": \"amazon: casque\"}], "
    "\"refus\": \"\"}\n"
    "« itinéraire vers la gare de Lyon » -> {\"etapes\": [{\"outil\": \"recherche\", \"arg\": \"itineraire: gare de Lyon\"}], "
    "\"refus\": \"\"}\n"
    "« dis dans le salon blabla que le film commence à 20 h 30 » -> {\"etapes\": [{\"outil\": \"discord_message\", "
    "\"arg\": \"dans blabla, le film commence à 20 h 30\"}], \"refus\": \"\"}\n"
    "- Pour un message Discord : UNE seule étape discord_message, le message recopié en entier, rien d'autre "
    "(pas de timer, pas de salon vocal).\n"
    "Exemples de refus :\n"
    "« supprime mes fichiers » -> {\"etapes\": [], \"refus\": \"Je ne touche pas aux fichiers.\"}\n"
    "« achète ce livre » -> {\"etapes\": [], \"refus\": \"Je ne fais pas de paiement.\"}\n"
    "« éteins l'ordinateur » -> {\"etapes\": [], \"refus\": \"Je ne sais pas éteindre l'ordinateur.\"}\n"
    "- N'invente aucun outil. Réponds uniquement par le JSON demandé."
)

# Garde-fous du code, quoi que dise le modèle (demande de l'utilisateur, 17/11) : JAMAIS modifier de fichiers,
# éteindre / redémarrer l'ordinateur ou changer ses réglages. Aucun outil ne le fait, et les outils génériques
# (touches, applis, texte) sont bridés pour qu'aucune combinaison n'y mène.
BLOCKED_APPS = re.compile(
    r"\b(cmd|invite de commandes|powershell|terminal|console|regedit|registre|explorateur|explorer|fichiers"
    r"|gestionnaire|taskmgr|param[eè]tres|settings|r[eé]glages|panneau de configuration|control|msconfig"
    r"|configuration|services|gpedit|strat[eé]gie|diskpart|disques?|partition|bios|uefi|mise[s]? [aà] jour|update"
    r"|s[eé]curit[eé]|defender|pare-feu|firewall|alimentation|power|arr[eê]t|shutdown|red[eé]marr|veille|sleep"
    r"|d[eé]sinstall|uninstall|installer|setup|nettoyage|cleanup|corbeille|recycle|sauvegarde|backup"
    r"|r[eé]cup[eé]ration|recovery|ex[eé]cuter|run|wsl|bash|python|ollama|motionzero|iris)\b", re.I)
# touches permises : navigation et lecture seulement. Pas de Windows (Win+X : arrêter), pas d'Alt+F4,
# pas de Suppr, pas de Ctrl+S / Ctrl+Maj+Échap… : tout le reste est refusé.
SAFE_SINGLE = {"enter", "escape", "space", "tab", "up", "down", "left", "right", "pageup", "pagedown", "home",
               "end", "f5", "backspace"} | set("abcdefghijklmnopqrstuvwxyz0123456789")
SAFE_COMBOS = {("ctrl", "t"), ("ctrl", "w"), ("ctrl", "l"), ("ctrl", "tab"), ("ctrl", "shift", "tab"),
               ("alt", "tab"), ("alt", "left"), ("alt", "right"), ("ctrl", "plus"), ("ctrl", "minus"),
               ("ctrl", "f"), ("shift", "tab")}
BLOCKED_TEXT = re.compile(r"(^|[\s&|;])(del|erase|rd|rmdir|rm|format|shutdown|reg|taskkill|powershell|cmd|curl|"
                          r"iwr|wget)(\s|$)|[a-z]:\\|\\\\", re.I)

SCHEMA = {
    "type": "object",
    "properties": {
        "etapes": {"type": "array", "maxItems": MAX_STEPS, "items": {
            "type": "object",
            "properties": {"outil": {"type": "string", "enum": list(TOOLS)}, "arg": {"type": "string"}},
            "required": ["outil", "arg"]}},
        "refus": {"type": "string"},
    },
    "required": ["etapes", "refus"],
}


class PlanError(Exception):
    """Plan refusé : le message est montré tel quel."""


# ---------------------------------------------------------------- modèle local
def _http(url, data=None, timeout=5):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_ollama(wait_s=15.0):
    """Ollama répond ? Sinon le lance (sans fenêtre) et attend. False s'il est introuvable."""
    try:
        _http(OLLAMA + "/api/version", timeout=2)
        return True
    except Exception:
        pass
    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0))
    except OSError:
        log.exception("ollama introuvable")
        return False
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(0.5)
        try:
            _http(OLLAMA + "/api/version", timeout=2)
            return True
        except Exception:
            continue
    return False


def ask_local(phrase):
    """Plan brut (dict) du modèle local pour la phrase. Lève RuntimeError si le modèle est indisponible."""
    if not ensure_ollama():
        raise RuntimeError("modèle local indisponible (Ollama)")
    try:
        out = _http(OLLAMA + "/api/chat", {
            "model": MODEL, "stream": False, "think": False, "keep_alive": KEEP_ALIVE, "format": SCHEMA,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": phrase}],
        }, timeout=LLM_TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"modèle {MODEL} absent (ollama pull {MODEL})") from exc
        raise RuntimeError(f"modèle local en erreur ({exc.code})") from exc
    except Exception as exc:
        raise RuntimeError("modèle local injoignable") from exc
    return json.loads(out["message"]["content"])


# ---------------------------------------------------------------- plan : vérification (pur, testable)
def parse_keys(arg):
    """« ctrl+t » -> ["ctrl", "t"] ; None si une touche est inconnue."""
    from .output import VK
    keys = []
    for k in re.split(r"\s*\+\s*", arg.strip().lower()):
        k = KEY_NAMES.get(k, k)
        if k not in VK:
            return "interdit"                 # touche hors liste : refusée comme une interdite
        keys.append(k)
    if not keys:
        return None
    ok = (len(keys) == 1 and keys[0] in SAFE_SINGLE) or tuple(keys) in SAFE_COMBOS
    return keys if ok else "interdit"


def normalize_url(arg):
    u = arg.strip().strip(".")
    if not u or " " in u or "." not in u:
        return None
    if not re.match(r"^https?://", u):
        u = "https://" + u
    return u if urllib.parse.urlparse(u).scheme in ("http", "https") else None


def check_step(outil, arg, app_names=None, ctx=None):
    """(outil, argument préparé, libellé) ou PlanError. app_names : applis connues (None : pas vérifié)."""
    arg = (arg or "").strip()
    if outil not in TOOLS:
        raise PlanError(f"outil inconnu : {outil}")
    if outil in ("ouvre_app", "ferme_app"):
        if not arg:
            raise PlanError("appli sans nom")
        if BLOCKED_APPS.search(arg):
            raise PlanError(f"interdit : {arg}")
        name = arg
        if app_names is not None:
            from .apps import best_match
            name = best_match(arg, app_names)
            if not name and outil == "ouvre_app":
                from .outils import known_site
                url = known_site(arg, (ctx or {}).get("favoris"))
                if url:                      # pas installée mais site connu (Netflix…) : le site
                    return "site", url, f"Ouvrir {arg} (site)"
            if not name:
                raise PlanError(f"appli introuvable : {arg}")
            if BLOCKED_APPS.search(name):
                raise PlanError(f"interdit : {name}")
        return outil, name, ("Ouvrir " if outil == "ouvre_app" else "Fermer ") + name
    if outil == "site":
        if not arg:
            raise PlanError("site sans nom")
        url = normalize_url(arg)
        if url is None:
            from .outils import known_site
            url = known_site(arg, (ctx or {}).get("favoris"))
        if url is None:                      # inconnu : cherché sur internet au moment de l'ouvrir, puis retenu
            return outil, ("?", arg), f"Ouvrir {arg} (cherché sur internet)"
        return outil, url, f"Ouvrir {arg if ' ' in arg or '.' not in arg else url}"
    if outil in ("recherche_web", "youtube", "youtube_chaine", "rappel"):
        if not arg:
            raise PlanError(f"{outil} sans texte")
        return outil, arg, {"recherche_web": f"Rechercher « {arg} » sur Google",
                            "youtube": f"YouTube : 1re vidéo pour « {arg} »",
                            "youtube_chaine": f"YouTube : dernière vidéo de « {arg} »",
                            "rappel": f"Rappel « {arg} » (à valider)"}[outil]
    if outil == "touche":
        keys = parse_keys(arg)
        if keys == "interdit":
            raise PlanError(f"interdit : touche {arg}")
        if keys is None:
            raise PlanError(f"touche inconnue : {arg}")
        return outil, keys, "Touche " + "+".join(keys)
    if outil == "ecris":
        if not arg:
            raise PlanError("rien à écrire")
        if BLOCKED_TEXT.search(arg):
            raise PlanError("interdit : ressemble à une commande")
        return outil, arg, f"Écrire « {arg} »"
    if outil == "volume":
        from .volume import parse_volume
        cmd = parse_volume(arg)
        if cmd is None:
            raise PlanError(f"volume incompris : {arg}")
        return outil, cmd, f"Volume : {arg}"
    if outil == "discord":
        act = {"coupe": "discord_mute", "allume": "discord_unmute", "sourdine": "discord_deafen"}.get(arg.lower())
        if act is None:
            raise PlanError(f"discord : {arg} ?")
        return outil, act, f"Discord : {arg.lower()}"
    if outil == "timer":
        from .timers import parse_duration
        if not parse_duration(arg):
            raise PlanError(f"durée incomprise : {arg}")
        return outil, arg, f"Timer {arg}"
    if outil == "traducteur":
        return outil, "", "Traducteur (allume / éteint)"
    if outil == "chronometre":
        return outil, "", "Chronomètre (démarre / arrête)"
    r = _check_more(outil, arg, app_names, ctx or {})
    if r is not None:
        return r
    # attends
    try:
        s = float(arg.replace(",", ".").split()[0])
    except (ValueError, IndexError):
        raise PlanError(f"attente incomprise : {arg}") from None
    s = max(0.5, min(10.0, s))
    return outil, s, f"Attendre {s:g} s"


def _app(arg, app_names):
    """Nom d'appli vérifié (interdits compris), comme pour ouvre_app."""
    return check_step("ouvre_app", arg, app_names)[1]


def _check_more(outil, arg, app_names, ctx):
    """Outils ajoutés (routines, favoris, navigateur, fenêtres, infos) ; None si l'outil n'est pas l'un d'eux."""
    from . import outils as o
    favs, routines = ctx.get("favoris"), ctx.get("routines")
    needs_text = {"historique", "historique_video", "onglet", "ferme_onglets", "meteo", "heure_ville",
                  "conversion", "oublie_routine", "devant"}
    if outil in needs_text and not arg:
        raise PlanError(f"{outil} : il manque le texte")
    if outil in EXPANDING or outil == "cree_routine":
        raise PlanError(f"{outil} mal placé")
    if outil == "aide":
        return outil, "", "Exemples"
    if outil == "oublie_routine":
        store = routines
        if store is None or store.get(arg) is None:
            raise PlanError(f"inconnu : {arg}")
        return outil, arg, "Oublier la routine « " + arg + " »"
    if outil == "recherche":
        url = o.search_url(arg)
        if url is None:
            raise PlanError(f"recherche incomprise : {arg} (site: texte)")
        return outil, url, f"Rechercher {arg}"
    if outil in ("historique", "historique_video"):
        return outil, arg, ("Rouvrir la vidéo vue : « " if outil == "historique_video" else "Rouvrir la page : « ") + arg + " »"
    if outil == "onglet":
        return outil, arg, f"Onglet « {arg} »"
    if outil == "ferme_onglets":
        return outil, arg, f"Fermer les onglets « {arg} »"
    if outil == "rouvre_onglet":
        return outil, "", "Rouvrir le dernier onglet fermé"
    if outil == "video":
        keys = o.video_keys(arg)
        if keys is None:
            raise PlanError(f"vidéo : {arg} ?")
        return outil, keys, f"Vidéo : {arg}"
    if outil == "musique":
        vk = o.media_vk(arg)
        if vk is None:
            raise PlanError(f"musique : {arg} ?")
        return outil, vk, f"Musique : {arg}"
    if outil == "devant":
        name = _app(arg, app_names)
        return outil, name, f"{name} au premier plan"
    if outil == "fenetre":
        pair = o.split_pair(arg, (":", "=", "|"))
        side = o.norm_name(pair[1]) if pair else ""
        side = {"plein ecran": "plein", "agrandie": "plein", "a gauche": "gauche", "a droite": "droite"}.get(side, side)
        if side not in ("gauche", "droite", "plein"):
            raise PlanError(f"fenêtre incomprise : {arg} (nom: gauche / droite / plein)")
        name = _app(pair[0], app_names)
        return outil, (name, side), f"{name} : {side}"
    if outil == "calcul":
        try:
            o.calc(arg)
        except (ValueError, ZeroDivisionError, SyntaxError):
            raise PlanError(f"calcul incompris : {arg}") from None
        return outil, arg, f"Calcul : {arg}"
    if outil in ("meteo", "heure_ville", "conversion"):
        return outil, arg, {"meteo": "Météo : ", "heure_ville": "Heure à ", "conversion": "Conversion : "}[outil] + arg
    if outil == "agenda":
        return outil, "", "Rappels à venir"
    if outil == "discord_salon":
        if not arg:
            raise PlanError("salon sans nom")
        return outil, arg, f"Discord : aller dans le salon « {arg} »"
    if outil == "discord_message":
        if not re.match(r"^(dans|à|a|pour)\s+\S.*,\s*\S", arg, re.I):
            raise PlanError(f"message incompris : {arg} (dans <salon>, <message>)")
        return outil, arg, f"Discord : envoyer « {arg} »"
    return None


def expand(steps, routines=None, last=None):
    """Remplace « routine » et « refais » par leurs étapes (un seul niveau). Pur."""
    out = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("outil") == "routine":
            got = routines.get(s.get("arg") or "") if routines is not None else None
            if not got:
                raise PlanError(f"routine inconnue : {s.get('arg')}")
            out += [x for x in got if x.get("outil") not in EXPANDING]
        elif s.get("outil") == "refais":
            if not last:
                raise PlanError("aucune instruction à refaire")
            out += [x for x in last if x.get("outil") not in EXPANDING]
        else:
            out.append(s)
    return out


def check_plan(raw, app_names=None, ctx=None):
    """Plan du modèle -> [(outil, arg, libellé)] ; PlanError (refus du modèle compris).
    ctx : {"routines", "favoris" (magasins), "last" (étapes brutes de la dernière instruction réussie)}."""
    plan, _ = check_plan_raw(raw, app_names, ctx)
    return plan


def check_plan_raw(raw, app_names=None, ctx=None):
    """Comme check_plan, et rend aussi les étapes brutes (après routines) pour « refais »."""
    ctx = ctx or {}
    if not isinstance(raw, dict):
        raise PlanError("réponse illisible")
    steps = raw.get("etapes") or []
    if not steps:
        raise PlanError((raw.get("refus") or "rien à faire").strip())
    if len(steps) > MAX_STEPS:
        raise PlanError("plan trop long")
    create = [s for s in steps if isinstance(s, dict) and s.get("outil") == "cree_routine"]
    if create:                               # « crée la routine X : … » : les autres étapes sont retenues, pas faites
        name = (create[0].get("arg") or "").strip()
        others = [s for s in steps if isinstance(s, dict) and s.get("outil") != "cree_routine"]
        if not name or not others:
            raise PlanError("routine sans nom ou sans étape")
        if any(s.get("outil") in EXPANDING for s in others):
            raise PlanError("une routine ne peut pas en contenir une autre")
        labels = [check_step(s.get("outil"), s.get("arg"), app_names, ctx)[2] for s in others]
        clean = [{"outil": s.get("outil"), "arg": (s.get("arg") or "").strip()} for s in others]
        return ([("cree_routine", (name, clean), f"Enregistrer la routine « {name} » : " + " ; ".join(labels))],
                None)
    flat = expand(steps, ctx.get("routines"), ctx.get("last"))
    if len(flat) > 2 * MAX_STEPS:
        raise PlanError("plan trop long")
    plan = [check_step(s.get("outil"), s.get("arg"), app_names, ctx) for s in flat]
    return plan, [{"outil": s.get("outil"), "arg": (s.get("arg") or "").strip()} for s in flat]


# ---------------------------------------------------------------- YouTube sans navigateur ni clic
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr-FR",
                                               "Cookie": "SOCS=CAI; CONSENT=YES+1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", "replace")


def first_video_id(html):
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    return m.group(1) if m else None


def youtube_first(query, get=_get):
    vid = first_video_id(get("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)))
    if not vid:
        raise RuntimeError("aucune vidéo trouvée")
    return "https://www.youtube.com/watch?v=" + vid


def youtube_latest(channel, get=_get):
    html = get("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(channel))
    m = re.search(r'"canonicalBaseUrl":"(/@[^"]+)"', html)
    if not m:
        raise RuntimeError("chaîne introuvable")
    vid = first_video_id(get("https://www.youtube.com" + m.group(1) + "/videos"))
    if not vid:
        raise RuntimeError("aucune vidéo sur la chaîne")
    return "https://www.youtube.com/watch?v=" + vid


# ---------------------------------------------------------------- orchestration
class Instructeur:
    """submit(audio) depuis la boucle ; events / actions / state appelés par la boucle principale seulement."""

    def __init__(self, transcribe, launcher=None, desk=None, ask=ask_local, open_url=None, runner=None,
                 routines=None, favoris=None, bot=None):
        self.transcribe, self.launcher, self.desk, self.ask = transcribe, launcher, desk, ask
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

    def _think(self, audio):
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
        try:
            raw = self.ask(phrase + self._context())
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
        else:
            raise RuntimeError(f"outil sans action : {outil}")
        return None

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
