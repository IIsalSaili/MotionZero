"""« iris instruction » (#45) : une phrase libre -> Whisper -> modèle local (Ollama) -> plan d'actions d'Iris : constantes et fonctions (1/2, découpé de instruction.py, #52)."""
import json
import logging
import re
import subprocess
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


OLLAMA_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # console cachée, héritée par ses enfants


def is_help(phrase):
    from .outils import norm_name
    p = norm_name(phrase)
    return any(w in p for w in HELP_WORDS) and len(p) < 60


# Faits sans « oui » quand le plan ne contient qu'eux (choix de l'utilisateur, 17/11) : les commandes qui
# existaient seules avant (ouvre, rappel, volume). Tout autre outil dans le plan, Discord
# compris (26/11) : « oui » obligatoire pour l'ensemble.
DIRECT = {"ouvre_app", "site", "rappel", "volume"}   # 26/11 : timer et chronomètre redevenus des mots à part
CONFIRM_S = 10.0          # sans « oui » dans ce temps : plan annulé (jamais lancé seul)
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
    "youtube": "ouvre directement la 1re vidéo YouTube trouvée pour une recherche (arg : la recherche ; pour une vidéo "
               "précise d'une chaîne : le nom de la chaîne puis le sujet)",
    "touche": "appuie sur une touche ou un raccourci (arg : ex. « entrée », « ctrl+t », « alt+tab », « f5 »)",
    "ecris": "écrit un texte là où se trouve le curseur (arg : le texte)",
    "volume": "règle le son du PC (arg : « 40 », « plus fort », « moins fort », « coupe », « remets »)",
    "discord": "micro Discord (arg : « coupe », « allume » ou « sourdine »)",
    "discord_salon": "te déplace dans un salon vocal Discord (arg : le nom du salon)",
    "discord_message": "envoie un message Discord par le bot (arg : « dans <salon ou personne>, <le message> »)",
    "discord_raccroche": "quitte le salon vocal Discord, raccroche (arg vide)",
    "discord_muet": "coupe ou rend le micro d'un membre sur le serveur Discord (arg : son nom)",
    "discord_sourd": "rend sourd un membre sur le serveur Discord, ou lui rend le son (arg : son nom)",
    "discord_deconnecte": "déconnecte un membre du salon vocal Discord (arg : son nom)",
    "discord_kick": "expulse (kick) un membre du serveur Discord (arg : son nom)",
    "discord_pseudo": "change le pseudo d'un membre Discord (arg : « nom: nouveau pseudo »)",
    "discord_donne_role": "donne un rôle à un membre Discord (arg : « nom: rôle »)",
    "discord_retire_role": "retire un rôle à un membre Discord (arg : « nom: rôle »)",
    "rappel": "crée un rappel, à valider ensuite (arg : la demande, ex. « demain 9 h appeler le médecin »)",
    "traducteur": "allume ou éteint les sous-titres traduits du son du PC (arg vide)",
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
    "- Pour une vidéo YouTube, utilise youtube directement (il ouvre eux-mêmes le navigateur) : "
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
    "« kick Paul » -> {\"etapes\": [{\"outil\": \"discord_kick\", \"arg\": \"Paul\"}], \"refus\": \"\"}\n"
    "« donne le rôle chef à Paul » -> {\"etapes\": [{\"outil\": \"discord_donne_role\", \"arg\": \"Paul: chef\"}], "
    "\"refus\": \"\"}\n"
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
                         # console cachée seulement : ses enfants (gpu-discover, llama-server) la reprennent.
                         # DETACHED_PROCESS (sans console) leur faisait ouvrir chacun une fenêtre (18/11).
                         creationflags=OLLAMA_FLAGS)
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
    if outil in ("recherche_web", "youtube", "rappel"):
        if not arg:
            raise PlanError(f"{outil} sans texte")
        return outil, arg, {"recherche_web": f"Rechercher « {arg} » sur Google",
                            "youtube": f"YouTube : 1re vidéo pour « {arg} »",
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
    if outil == "traducteur":
        return outil, "", "Traducteur (allume / éteint)"
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
    if outil in MEMBER_TOOLS:
        return _check_member(outil, arg)
    return None


# outil -> (action envoyée au bot, libellé) ; {n} : le membre, {v} : la valeur (pseudo, rôle)
MEMBER_TOOLS = {
    "discord_raccroche": ("hangup", "Discord : raccrocher"),
    "discord_muet": ("mute", "Discord : micro de {n} (coupe / rend)"),
    "discord_sourd": ("deafen", "Discord : son de {n} (coupe / rend)"),
    "discord_deconnecte": ("disconnect", "Discord : déconnecter {n} du vocal"),
    "discord_kick": ("kick", "Discord : expulser {n} du serveur"),
    "discord_pseudo": ("nick", "Discord : pseudo de {n} -> « {v} »"),
    "discord_donne_role": ("role_add", "Discord : donner le rôle « {v} » à {n}"),
    "discord_retire_role": ("role_remove", "Discord : retirer le rôle « {v} » à {n}"),
}


def _check_member(outil, arg):
    """(outil, ordre pour le bot, libellé) ; le bot cherche lui-même le membre et le rôle."""
    from .outils import split_pair
    action, label = MEMBER_TOOLS[outil]
    if action == "hangup":
        return outil, {"action": action}, label
    who, value = arg.strip(" ."), ""
    if action in ("nick", "role_add", "role_remove"):
        pair = split_pair(arg, (":", "=", "|"))
        if not pair or not pair[0].strip() or not pair[1].strip():
            raise PlanError(f"{outil} : il faut « nom: {'pseudo' if action == 'nick' else 'rôle'} »")
        who, value = pair[0].strip(" ."), pair[1].strip(" .")
    if not who:
        raise PlanError(f"{outil} : il manque le nom")
    return outil, {"action": action, "who": who, "value": value}, label.format(n=who, v=value)
