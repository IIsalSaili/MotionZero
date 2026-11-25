"""« iris instruction » (#45) : une phrase libre -> Whisper -> modèle local (Ollama) -> plan d'actions d'Iris : constantes et fonctions (2/2, découpé de instruction.py, #52)."""
import json
import logging
import re
import urllib.parse
import urllib.request

from .instruction_base import (_check_more, _http, EXPANDING, KEEP_ALIVE, LLM_TIMEOUT_S, MAX_STEPS, MODEL, OLLAMA, PlanError,
                               SCHEMA, SYSTEM, UA, check_step, ensure_ollama)

log = logging.getLogger("motionzero.instruction")




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


def warm_local():
    """Démarre Ollama si besoin et charge le modèle sur la carte graphique, sans question (#76).
    Appelé dès « iris instruction » : le chargement (~4 s) se fait pendant que l'utilisateur parle. Ne lève jamais."""
    try:
        if ensure_ollama():
            _http(OLLAMA + "/api/generate", {"model": MODEL, "keep_alive": KEEP_ALIVE}, timeout=LLM_TIMEOUT_S)
            return True
    except Exception:
        log.warning("prechargement du modele local impossible", exc_info=True)
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
