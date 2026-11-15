"""« iris quota » : pourcentage utilisé de la session Claude de 5 heures, et l'heure du reset.

Affiché en permanence dans le coin haut gauche, centré sur le bandeau, tant qu'il est allumé ; « iris quota »
l'allume ou l'éteint, et le choix est gardé dans quota.txt (non versionné).

Source : l'adresse que Claude Code lit lui-même pour /usage (non documentée), avec le jeton de connexion
de ~/.claude/.credentials.json, lu seulement, envoyé seulement à Anthropic. Si quoi que ce soit échoue
(pas de réseau, jeton expiré, format changé), on affiche « quota indisponible », jamais de plantage.
La lecture se fait dans un fil ; la boucle principale ne lit que le dernier résultat.
"""
import datetime
import json
import logging
import os
import threading
import urllib.request

URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
PERIOD_S = 300.0          # une lecture toutes les 5 minutes
RETRY_S = 60.0            # après un échec : nouvel essai plus tôt
TIMEOUT_S = 10.0

_log = logging.getLogger("motionzero")


def read_token(path=CREDENTIALS):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["claudeAiOauth"]["accessToken"]


def fetch(token, timeout=TIMEOUT_S):
    req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + token,
                                               "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _window(data, key):
    w = data[key]
    resets = w.get("resets_at")
    return float(w["utilization"]), datetime.datetime.fromisoformat(resets).astimezone() if resets else None


def parse(data):
    """Réponse -> ((% utilisé, reset) de la session 5 h, (% utilisé, reset) de la semaine, ou None).
    Heures en local. ValueError si le format de la session a changé ; la semaine absente ne bloque pas."""
    try:
        five = _window(data, "five_hour")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ValueError(f"réponse quota inattendue : {e}") from e
    try:
        week = _window(data, "seven_day")
    except (KeyError, TypeError, ValueError, AttributeError):
        week = None
    return five, week


def quota_text(pct, reset, now=None):
    """« 40 % · reset 22h59 » ; le jour est précisé si le reset n'est pas aujourd'hui."""
    if pct is None:
        return "Quota indisponible"
    text = f"{round(pct)} %"
    if reset is None:
        return text + " · pas de session"
    now = now or datetime.datetime.now().astimezone()
    if reset <= now:
        return text + " · reset passé"
    hm = f"{reset.hour}h{reset.minute:02d}"
    days = (reset.date() - now.date()).days
    if days == 1:
        hm = "demain " + hm
    elif 1 < days < 7:
        hm = JOURS[reset.weekday()] + " " + hm
    elif days >= 7:
        hm = reset.strftime("%d/%m ") + hm
    return f"{text} · reset {hm}"


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def read_shown(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "oui"
    except OSError:
        return False


def write_shown(path, shown):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("oui" if shown else "non")
    except OSError:
        _log.warning("choix du quota non enregistre")


class Quota:
    """Dernière lecture du quota, rafraîchie dans un fil tant que l'affichage est allumé."""

    def __init__(self, token_reader=read_token, fetcher=fetch):
        self.token_reader, self.fetcher = token_reader, fetcher
        self.five, self.week, self.ok = None, None, False
        self.loaded = False                   # au moins une lecture terminée (réussie ou non)
        self.next_t = -1e9
        self._busy = False
        self._lock = threading.Lock()

    def refresh_now(self):
        """Lecture synchrone (utilisée par le fil et les tests). Ne lève jamais."""
        try:
            five, week = parse(self.fetcher(self.token_reader()))
            ok = True
        except Exception as e:                # réseau, jeton, format : tout finit en « indisponible »
            _log.warning("quota illisible : %s", e)
            five, week, ok = None, None, False
        with self._lock:
            self.five, self.week, self.ok, self.loaded = five, week, ok, True
        return ok

    def tick(self, t, shown):
        """Appelé par la boucle principale : lance une lecture en fond quand c'est l'heure."""
        if not shown or self._busy or t < self.next_t:
            return
        self._busy = True

        def run():
            try:
                ok = self.refresh_now()
            finally:
                self._busy = False
            self.next_t = t + (PERIOD_S if ok else RETRY_S)

        self.next_t = t + PERIOD_S            # évite de relancer pendant la lecture
        threading.Thread(target=run, name="quota", daemon=True).start()

    def force(self):
        """« iris quota » qui allume : relire tout de suite."""
        self.next_t = -1e9

    def lines(self, now=None):
        """[(« 5 h », texte), (« Semaine », texte)] pour la pastille ; une seule ligne si rien de lisible."""
        with self._lock:
            if not self.loaded:
                return [("", "Quota…")]
            if not self.ok:
                return [("", "Quota indisponible")]
            out = [("5 h", quota_text(*self.five, now))]
            if self.week:
                out.append(("Semaine", quota_text(*self.week, now)))
            return out
