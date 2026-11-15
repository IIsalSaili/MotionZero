"""Recherche internet pour « iris question » : navigateur sans fenêtre (Chromium headless, Playwright).

Un seul appel au modèle : on cherche, on lit le texte des premières pages, on coupe, puis on l'envoie avec la
question (la recherche intégrée de Claude Code faisait plusieurs allers-retours : ~28 fois une question simple,
mesuré le 15/11). Startpage d'abord (résultats Google), Bing en secours ; DuckDuckGo, Mojeek, Brave bloquent le headless.
Toute panne (pas de réseau, blocage, page illisible) lève WebError : Iris répond alors sans internet.
"""
import base64
import logging
import re
import time
import urllib.parse

log = logging.getLogger("motionzero.web")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
PAGES = 2               # pages lues en entier (en plus des extraits de la page de résultats)
PAGE_CHARS = 5000       # texte gardé par page
TOTAL_CHARS = 12000     # plafond envoyé au modèle (~3 000 mots) : c'est lui qui fait le coût
PAGE_TIMEOUT_MS = 8000


# texte du contenu principal (article, main) plutôt que toute la page : les menus prenaient la place
MAIN_TEXT = """() => { const m = document.querySelector('article') || document.querySelector('main')
    || document.querySelector('[role=main]'); const el = (m && m.innerText.length > 300) ? m : document.body;
    return el.innerText }"""


class WebError(RuntimeError):
    pass


def bing_target(href):
    """Lien de résultat Bing (« bing.com/ck/a?…&u=a1<base64> ») -> adresse réelle ; autre lien : inchangé."""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        u = q.get("u", [""])[0]
        if "bing.com" in href and u.startswith("a1"):
            raw = u[2:]
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        pass
    return href


def clean(text, limit):
    """Espaces repliés, lignes vides retirées, coupé à limit caractères."""
    lines = (re.sub(r"[ \t\xa0]+", " ", l).strip() for l in (text or "").splitlines())
    out = "\n".join(l for l in lines if len(l) > 2)
    return out[:limit]


ENGINES = [
    # Startpage : résultats de Google, extraits riches (le titre contient une balise <style> : retirée)
    ("startpage", "https://www.startpage.com/do/search?q={q}&language=francais",
     """() => [...document.querySelectorAll('div.result')].map(r => {
            const a = r.querySelector('a.result-title, a.result-link'); const d = r.querySelector('p.description');
            if (!a) return null; const c = a.cloneNode(true); c.querySelectorAll('style').forEach(x => x.remove());
            return [c.textContent, a.href, d ? d.textContent : ''] }).filter(Boolean)"""),
    # Bing : en secours (résultats parfois hors sujet en headless : « dernier match PSG » -> dictionnaires)
    ("bing", "https://www.bing.com/search?q={q}&setlang=fr&cc=FR",
     """() => [...document.querySelectorAll('li.b_algo')].map(li => {
            const a = li.querySelector('h2 a'); const p = li.querySelector('.b_caption p, p');
            return a ? [a.textContent, a.href, p ? p.textContent : ''] : null }).filter(Boolean)"""),
]


def _results(page, query):
    for name, url, js in ENGINES:
        try:
            page.goto(url.format(q=urllib.parse.quote_plus(query)), timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
            try:                                       # résultats ajoutés après le chargement
                page.wait_for_selector("div.result, li.b_algo", timeout=4000)
            except Exception:
                pass
            rows = page.evaluate(js)
        except Exception as exc:                       # moteur bloqué ou trop lent : le suivant
            log.warning("recherche %s impossible : %s", name, str(exc)[:80])
            continue
        rows = [(t.strip(), bing_target(h), s.strip()) for t, h, s in rows if h.startswith("http")]
        if rows:
            return name, rows[:6]
        log.warning("recherche %s : aucun resultat", name)
    raise WebError("aucun moteur de recherche n'a répondu")


def research(query):
    """Texte à donner au modèle : extraits des résultats puis texte des premières pages, avec leurs sources."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WebError("navigateur absent (playwright)") from exc
    t0 = time.perf_counter()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(locale="fr-FR", user_agent=UA)
                engine, rows = _results(page, query)
                parts = ["Résultats de recherche :"] + [f"- {t} ({h}) : {s}" for t, h, s in rows]
                read = 0
                for title, href, _ in rows:
                    if read >= PAGES:
                        break
                    try:
                        page.goto(href, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
                        text = clean(page.evaluate(MAIN_TEXT), PAGE_CHARS)
                    except Exception as exc:          # page lente ou protégée : la suivante
                        log.info("page illisible %s : %s", href[:80], str(exc)[:60])
                        continue
                    if len(text) > 200:
                        parts.append(f"\nPage « {title} » ({urllib.parse.urlparse(href).netloc}) :\n{text}")
                        read += 1
            finally:
                browser.close()
    except WebError:
        raise
    except Exception as exc:
        raise WebError(f"navigateur en panne : {str(exc)[:80]}") from exc
    context = "\n".join(parts)[:TOTAL_CHARS]
    log.info("recherche « %s » : %s, %d pages lues, %d caracteres, %.1f s", query, engine, read, len(context),
             time.perf_counter() - t0)
    return context
