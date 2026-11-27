"""Outils supplémentaires d'« iris instruction » (#45) : routines, favoris, vidéo, onglets, historique, infos, : constantes et fonctions (2/2, découpé de outils.py, #52)."""
import logging
import re
import urllib.parse
import urllib.request

from .outils_base import WMO, _get_json, fmt_num, norm_name

log = logging.getLogger("motionzero.outils")


def weather(city, get=_get_json):
    """Météo actuelle et du jour (Open-Meteo, gratuit, sans clé)."""
    g = get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=fr&name="
            + urllib.parse.quote(city.strip()))
    if not g.get("results"):
        raise RuntimeError(f"ville introuvable : {city}")
    p = g["results"][0]
    w = get(f"https://api.open-meteo.com/v1/forecast?latitude={p['latitude']}&longitude={p['longitude']}"
            "&current=temperature_2m,weather_code&daily=temperature_2m_min,temperature_2m_max,"
            "precipitation_probability_max&timezone=auto&forecast_days=1")
    cur, day = w["current"], w["daily"]
    return (f"{p['name']} : {round(cur['temperature_2m'])} °C, {WMO.get(cur['weather_code'], 'temps variable')} "
            f"(min {round(day['temperature_2m_min'][0])}, max {round(day['temperature_2m_max'][0])}, "
            f"pluie {day['precipitation_probability_max'][0]} %)")


CURRENCIES = {"euro": "EUR", "euros": "EUR", "eur": "EUR", "dollar": "USD", "dollars": "USD", "usd": "USD",
              "livre sterling": "GBP", "livres sterling": "GBP", "gbp": "GBP", "yen": "JPY", "yens": "JPY",
              "franc suisse": "CHF", "francs suisses": "CHF", "chf": "CHF", "dirham": "MAD", "dirhams": "MAD",
              "dollar canadien": "CAD", "dollars canadiens": "CAD", "cad": "CAD"}


def money(arg, get=_get_json):
    m = re.match(r"\s*([\d.,]+)\s*(.+?)\s+(?:en|vers)\s+(.+?)\s*$", arg, re.I)
    if not m:
        raise ValueError("conversion incomprise")
    a, b = CURRENCIES.get(norm_name(m.group(2))), CURRENCIES.get(norm_name(m.group(3)))
    if not a or not b:
        raise ValueError("devise inconnue")
    v = float(m.group(1).replace(",", "."))
    if a == b:
        return f"{fmt_num(v)} {a}"
    if "MAD" in (a, b):        # le dirham n'est pas sur l'API de la BCE : open.er-api
        rate = get(f"https://open.er-api.com/v6/latest/{a}")["rates"][b]
    else:
        rate = get(f"https://api.frankfurter.app/latest?from={a}&to={b}")["rates"][b]
    return f"{fmt_num(v)} {a} = {fmt_num(round(v * rate, 2))} {b}"


# ---------------------------------------------------------------- sites connus d'office (aucun favori à retenir)
SITES = {
    "mails": "https://mail.google.com", "mes mails": "https://mail.google.com", "gmail": "https://mail.google.com",
    "mail": "https://mail.google.com", "boite mail": "https://mail.google.com",
    "outlook": "https://outlook.live.com", "hotmail": "https://outlook.live.com",
    "youtube": "https://www.youtube.com", "netflix": "https://www.netflix.com", "twitch": "https://www.twitch.tv",
    "prime video": "https://www.primevideo.com", "disney": "https://www.disneyplus.com",
    "disney plus": "https://www.disneyplus.com", "crunchyroll": "https://www.crunchyroll.com",
    "spotify": "https://open.spotify.com", "deezer": "https://www.deezer.com",
    "amazon": "https://www.amazon.fr", "leboncoin": "https://www.leboncoin.fr", "vinted": "https://www.vinted.fr",
    "discord": "https://discord.com/app", "whatsapp": "https://web.whatsapp.com", "messenger": "https://www.messenger.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com", "x": "https://x.com",
    "twitter": "https://x.com", "reddit": "https://www.reddit.com", "linkedin": "https://www.linkedin.com",
    "tiktok": "https://www.tiktok.com", "github": "https://github.com", "chatgpt": "https://chatgpt.com",
    "google": "https://www.google.com", "maps": "https://www.google.com/maps", "google maps": "https://www.google.com/maps",
    "agenda": "https://calendar.google.com", "google agenda": "https://calendar.google.com",
    "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "traduction": "https://translate.google.com", "google traduction": "https://translate.google.com",
    "wikipedia": "https://fr.wikipedia.org", "meteo": "https://meteofrance.com", "doctolib": "https://www.doctolib.fr",
    "ameli": "https://www.ameli.fr", "caf": "https://www.caf.fr", "impots": "https://www.impots.gouv.fr",
    "la poste": "https://www.laposte.fr", "sncf": "https://www.sncf-connect.com", "ratp": "https://www.ratp.fr",
    "uber eats": "https://www.ubereats.com", "deliveroo": "https://deliveroo.fr", "steam": "https://store.steampowered.com",
}


def _ddg(query, timeout=8):
    """Adresse du 1er résultat (DuckDuckGo en HTML simple, une requête) ; None si rien."""
    import html as _html
    req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query),
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        page = r.read().decode("utf-8", "replace")
    for u in re.findall(r'class="result__a" href="([^"]+)"', page):
        u = _html.unescape(u)
        real = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("uddg", [u])[0]
        if real.startswith("http") and "duckduckgo.com" not in real:
            return real
    return None


def known_site(name, favs=None):
    """Adresse d'un site par son nom : favoris retenus, puis sites connus d'office ; None sinon. Pur."""
    n = norm_name(name)
    n2 = re.sub(r"^(le |la |les |l'|mon |ma |mes |site (de |du )?)", "", n)
    for key in (n, n2):
        if favs is not None and favs.get(key):
            return favs.get(key)
        if key in SITES:
            return SITES[key]
    return None


def find_site(name, favs=None, search=_ddg):
    """(adresse, trouvée par recherche ?) : favoris, sites connus, sinon 1er résultat d'une recherche ;
    en dernier recours la page de recherche Google (jamais d'échec muet)."""
    url = known_site(name, favs)
    if url:
        return url, False
    try:
        url = search(name + " site officiel")
    except Exception:
        log.warning("recherche du site %s impossible", name)
        url = None
    if url:
        return url, True
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(name), False


# ---------------------------------------------------------------- exemples montrés à l'utilisateur
EXAMPLES = [   # carte d'aide : une phrase par ligne, à dire telle quelle après « iris instruction »
    "« ouvre mes mails »",
    "« mets la vidéo de Squeezie sur Minecraft »",
    "« mets Chrome à gauche et Discord à droite »",
    "« mets le son à 30 et coupe mon micro Discord »",
    "« dis dans général que j'arrive »",
    "« kick Paul »",
    "« rappelle-moi demain à 9 h d'appeler le médecin »",
    "« crée la routine travail : ouvre Discord »",
]
