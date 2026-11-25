"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN : constantes et fonctions (2/2, découpé de cvgen.py, #52)."""
import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .cvgen_base import fmt_note, A_PARCOURIR, BASE, CvgenError, DIR, ETATS, ROUTES, ROUTE_TIMEOUT_S, TIMEOUT_S

log = logging.getLogger("motionzero.cvgen")


def _http(method, path, body=None, base=BASE, timeout=TIMEOUT_S):
    data = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(base + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except (ValueError, OSError):
            msg = None
        raise CvgenError(msg or f"CVGEN a refusé ({e.code})") from None
    except TimeoutError:
        raise CvgenError("CVGEN met trop de temps à répondre : réessaie") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise CvgenError("CVGEN met trop de temps à répondre : réessaie") from None
        raise CvgenError("CVGEN ne répond pas") from None
    except (OSError, ValueError):
        raise CvgenError("CVGEN ne répond pas") from None


def _launch(root=DIR):
    """Démarre `node server.mjs` sans fenêtre, détaché d'Iris (il survit à une relance d'Iris)."""
    node = shutil.which("node")
    if node is None or not (Path(root) / "server.mjs").exists():
        raise CvgenError("CVGEN introuvable sur ce PC")
    flags = 0x08000000 | 0x00000200   # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([node, "server.mjs"], cwd=str(root), creationflags=flags if os.name == "nt" else 0,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call(name, http=_http, body=None, **ids):
    method, path = ROUTES[name]
    path = path.format(**{k: urllib.parse.quote(str(v), safe="") for k, v in ids.items()})
    if http is _http:
        return _http(method, path, body, timeout=ROUTE_TIMEOUT_S.get(name, TIMEOUT_S))
    return http(method, path, body) if body is not None else http(method, path)


def a_parcourir(offres):
    """Offres à trier puis à vérifier, meilleure note en tête. Pur : testable."""
    def note(o):
        return (o.get("evaluation") or {}).get("globale") or 0
    out = [o for o in offres or [] if o.get("etat") in A_PARCOURIR]
    return sorted(out, key=lambda o: (list(A_PARCOURIR).index(o["etat"]), -note(o)))




def card(offres, i):
    """(titre, lignes) de l'offre i. Pur : testable."""
    if not offres:
        return "Aucune offre à trier ni à vérifier", ["« cherche » pour en trouver"]
    o = offres[i]
    ev = o.get("evaluation") or {}
    total = sum(1 for x in offres if x["etat"] == o["etat"])
    k = sum(1 for x in offres[:i + 1] if x["etat"] == o["etat"])
    title = f"Offre {k} / {total} {A_PARCOURIR[o['etat']]} · {fmt_note(ev.get('globale'))} / 5"
    lines = [f"{o.get('poste') or 'Poste ?'} · {o.get('entreprise') or 'entreprise ?'}"]
    if ev.get("verdict"):
        lines.append(f"{ev['verdict']} ({o.get('source') or 'site ?'})")
    axes = [a for a in ev.get("axes") or [] if isinstance(a.get("note"), (int, float))]
    if axes:
        fort, faible = max(axes, key=lambda a: a["note"]), min(axes, key=lambda a: a["note"])
        lines.append(f"+ {fort.get('libelle')} : {fort.get('detail', '')}"[:110])
        if faible is not fort:
            lines.append(f"- {faible.get('libelle')} : {faible.get('detail', '')}"[:110])
    return title, lines


def summary(agent, compte, prep):
    """Lignes de la carte « état ». Pur : testable."""
    etat = (agent or {}).get("etat")
    lines = ["Recherche en cours" if etat == "en-cours" else
             "Recherche en train de s'arrêter" if etat == "arret-demande" else "Recherche arrêtée"]
    counts = [f"{(compte or {}).get(k, 0)} {lbl}" for k, lbl in ETATS if (compte or {}).get(k)]
    lines.append(" · ".join(counts) if counts else "Aucune offre en attente")
    if (prep or {}).get("offreId"):
        lines.append("Une candidature est en préparation")
    msg = (agent or {}).get("message")
    if msg:
        lines.append(str(msg)[:80])
    return lines


QUESTION_MAX = 600        # caractères de la réponse proposée
PROMPT_QUESTION = """Tu aides un candidat à remplir un formulaire de candidature en ligne.
Réponds à la question ci-dessous à sa place, à la première personne, en français, en 2 à 4 phrases.
Pas de formule de politesse, pas de titre, rien d'inventé : appuie-toi seulement sur le profil et l'offre.

Offre : {poste} chez {entreprise}
{annonce}

Profil du candidat (JSON) :
{profil}

Question du formulaire : {question}
Réponse :"""
PRIVE = {"adresse", "code_postal", "date_naissance", "telephone", "email", "photo", "salaire_souhaite"}


def question_prompt(question, offre, profile, texte=None):
    """Message envoyé au modèle de CVGEN : offre + profil (sans adresse, téléphone…) + question. Pur."""
    prof = dict(profile or {})
    prof["identity"] = {k: v for k, v in (prof.get("identity") or {}).items() if k not in PRIVE}
    o = offre or {}
    return PROMPT_QUESTION.format(poste=o.get("poste") or "poste inconnu", entreprise=o.get("entreprise") or "?",
                                  annonce=str(texte or "")[:3000],
                                  profil=json.dumps(prof, ensure_ascii=False)[:5000], question=question)


def clean_answer(text):
    """Réponse du modèle : une ligne propre, bornée ; None si vide. Pur."""
    t = " ".join(str(text or "").split()).strip().strip('"«» ')
    if t.lower().startswith("réponse :"):
        t = t[9:].strip()
    return t[:QUESTION_MAX] or None


def offer_email(texte):
    """Adresse e-mail de candidature lue dans l'annonce ; None si absente. Pur."""
    import re
    for m in re.finditer(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(texte or "")):
        a = m.group(0).rstrip(".")
        if not a.lower().startswith(("noreply", "no-reply", "ne-pas-repondre")):
            return a
    return None


def draft_eml(to, offre, profile, attachments):
    """Brouillon .eml (X-Unsent : s'ouvre prêt à envoyer) avec les PDF joints. Pur sauf la lecture des PDF."""
    from email.message import EmailMessage
    ident = (profile or {}).get("identity") or {}
    nom = " ".join(x for x in (ident.get("prenom"), ident.get("nom")) if x) or "Candidat"
    o = offre or {}
    poste = o.get("poste") or "le poste proposé"
    chez = f" chez {o['entreprise']}" if o.get("entreprise") else ""
    m = EmailMessage()
    m["To"] = to
    m["Subject"] = f"Candidature : {poste}"
    m["X-Unsent"] = "1"
    sign = "\n".join(x for x in (nom, ident.get("telephone"), ident.get("email")) if x)
    m.set_content(f"Bonjour,\n\nJe vous adresse ma candidature au poste de {poste}{chez}. "
                  "Vous trouverez ci-joint mon CV et ma lettre de motivation.\n\n"
                  f"Je reste à votre disposition pour un échange.\n\nBien cordialement,\n{sign}\n")
    for path in attachments:
        m.add_attachment(Path(path).read_bytes(), maintype="application", subtype="pdf", filename=Path(path).name)
    return m.as_bytes()
