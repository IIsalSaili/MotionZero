"""Page d'accueil (issue #35, mise en page A « Tableau calme ») : ce qu'elle montre, calculé sans Qt (testable).

- bande du haut : état d'Iris (j'écoute, dictée, pause…), mode, souris ;
- « Ici, maintenant » : le bloc du mode en cours, tiré d'aide.py (même source que « iris aide ») ;
- capteurs et services : caméra, micro, Whisper, bot Discord, gardien ; une pastille chacun ;
- bas de page : consommation sur une ligne, dernières commandes comprises ou refusées.
Rien n'est écrit à la main ici qui puisse prendre du retard sur les commandes."""
from .aide import now_block
from .core import Mode

HOME_TITLE = "Iris"   # titre de la fenêtre d'accueil : « iris accueil » la retrouve par lui (vscode.py)
OK, OFF, IDLE, FAIL = "ok", "off", "idle", "fail"   # vert, orange (éteint exprès), gris (au repos), rouge (panne)

MODE_LABELS = {Mode.NEUTRAL: "NEUTRE", Mode.READING: "LECTURE", Mode.CHROME: "CHROME", Mode.DISABLED: "PAUSE"}
MOUSE_ROWS = [("iris clic", "clic gauche"), ("iris double", "double clic"), ("iris menu", "clic droit"),
              ("iris agrippe", "glisser (redis agrippe pour lâcher)"), ("iris scroll", "faire défiler")]
LAST_N = 3          # dernières commandes affichées
LAST_MAX_S = 60.0   # au-delà, une commande n'est plus « dernière »


def state_text(mode, listening=False, dictating=False, confirming=False, mic_muted=False, voice_on=True):
    """(texte, ton) de la bande du haut. Ton : listen | busy | off | idle."""
    if mode == Mode.DISABLED:
        return "En pause", "off"
    if not voice_on:
        return "Voix coupée", "off"
    if dictating:
        return "Dictée en cours", "busy"
    if confirming:
        return "Envoie ou annule ?", "busy"
    if mic_muted:
        return "Micro coupé", "off"
    if listening:
        return "J'écoute", "listen"
    return "Prêt", "idle"


def now_view(mode, mouse=False, calendar_open=False, confirming=False):
    """(titre, lignes) du bloc « Ici, maintenant ». Souris allumée hors Chrome : ses mots en tête."""
    title, rows = now_block(mode, calendar_open, confirming)
    if mouse and mode not in (Mode.CHROME, Mode.DISABLED) and not calendar_open and not confirming:
        return "Souris allumée", MOUSE_ROWS
    return title, rows


def sensors(cam_status="ok", voice_on=True, mic_muted=False, mic_stalled=False, whisper=False,
            bot_enabled=True, bot_connected=False, guard=True):
    """[(nom, état, détail)] des capteurs et services."""
    cam = (("Caméra", OK, "") if cam_status == "ok" else ("Caméra", FAIL, str(cam_status)))
    if not voice_on:
        mic = ("Micro", OFF, "voix coupée")
    elif mic_stalled:
        mic = ("Micro", FAIL, "aucun son")
    elif mic_muted:
        mic = ("Micro", OFF, "coupé")
    else:
        mic = ("Micro", OK, "")
    wh = ("Whisper", OK, "chargé") if whisper else ("Whisper", IDLE, "au repos")
    if not bot_enabled:
        bot = ("Bot Discord", OFF, "éteint")
    else:
        bot = ("Bot Discord", OK, "") if bot_connected else ("Bot Discord", FAIL, "injoignable")
    gd = ("Gardien", OK, "") if guard else ("Gardien", FAIL, "absent")
    return [cam, mic, wh, bot, gd]


def _nice(label):
    """« PAGE PRECEDENTE » -> « Page precedente » : les libellés du moteur sont en capitales."""
    return label[:1] + label[1:].lower() if label.isupper() else label


def last_commands(feed, rejected=None, now=0.0, n=LAST_N):
    """[(libellé, compris ?, âge en s)], la plus récente d'abord. feed : [(libellé, t)] ; rejected : (libellé, t)."""
    items = [(lab, "ignore" not in lab.lower(), t) for lab, t in (feed or [])]
    if rejected:
        items.append((rejected[0], False, rejected[1]))
    items = [(lab, ok, now - t) for lab, ok, t in items if 0 <= now - t <= LAST_MAX_S]
    items.sort(key=lambda it: it[2])
    return [(_nice(lab), ok, age) for lab, ok, age in items[:n]]


def conso_line(s):
    """Une ligne : « Iris 12 % CPU · 840 Mo · GPU 30 % · PC 34 % ». Vide tant qu'aucune mesure n'est venue."""
    if not s:
        return "Consommation : mesure en cours…"
    parts = [f"Iris {s.get('app_cpu', 0):.0f} % CPU", f"{s.get('app_private', 0):.0f} Mo"]
    if s.get("app_gpu") is not None:
        parts.append(f"GPU {s['app_gpu']:.0f} %")
    if s.get("pc_cpu") is not None:
        parts.append(f"PC {s['pc_cpu']:.0f} %")
    return " · ".join(parts)


def home_view(mode, mouse=False, pointer="main", listening=False, dictating=False, confirming=False,
              calendar_open=False, mic_muted=False, voice_on=True, sensor_list=None, feed=None, rejected=None,
              now=0.0):
    """Tout ce que la page affiche, en un dict (envoyé au fil Qt)."""
    state, tone = state_text(mode, listening, dictating, confirming, mic_muted, voice_on)
    title, rows = now_view(mode, mouse, calendar_open, confirming)
    return {"state": state, "tone": tone, "mode": MODE_LABELS.get(mode, str(mode)), "mouse": bool(mouse),
            "pointer": pointer, "now_title": title, "now_rows": rows, "sensors": sensor_list or [],
            "last": last_commands(feed, rejected, now)}
