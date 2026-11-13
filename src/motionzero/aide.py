"""« iris aide » : toutes les commandes, par thème, avec en tête ce qui marche dans le mode en cours.
(« iris guide », la documentation sur GitHub, est dans fenetre.py.)

Le contenu suit les tables de core.py : un test vérifie que chaque mot écouté y figure, pour que l'aide ne soit
plus en retard sur les commandes (l'ancienne en listait 20 sur 65). Effets courts : une ligne par commande."""
from .core import CHROME_KEYS, Mode

# (thème, [(mots à dire, effet)]) ; chaque mot est dit après « iris »
GROUPS = [
    ("Souris", [
        ("clic", "clic gauche"),
        ("double", "double clic"),
        ("menu", "clic droit"),
        ("glisse", "tenir le bouton"),
        ("lâche", "le relâcher"),
        ("défile", "monte / descends la main"),
        ("souris", "allume / éteint"),
        ("tête / main", "qui guide la souris"),
        ("centre", "curseur au centre"),
    ]),
    ("Texte", [
        ("type", "dictée au curseur"),
        ("entrée / envoie", "touche Entrée"),
        ("annule", "touche Échap"),
        ("espace", "touche Espace"),
        ("copie / colle", "Ctrl+C / Ctrl+V"),
        ("sélection", "tout sélectionner"),
        ("coupe", "couper"),
        ("efface", "le mot d'avant"),
        ("skip / back", "flèches"),
    ]),
    ("Fenêtres et applis", [
        ("plein écran", "aussi « agrandis »"),
        ("réduis", "fenêtre réduite"),
        ("gauche / droite", "sur une moitié"),
        ("tab", "fenêtre suivante"),
        ("ouvre / ferme", "puis le nom"),
        ("chrome", "Chrome et ses mots"),
        ("suivant / précédent", "onglet de VS Code"),
        ("discord", "Discord devant"),
        ("studio", "VS Code devant"),
        ("accueil", "accueil d'Iris"),
        ("volume", "puis « 40 »…"),
        ("réveil", "rallume l'écran"),
    ]),
    ("Claude", [
        ("claude", "micro dans VS Code"),
        ("question", "réponse en haut"),
    ]),
    ("Discord", [
        ("mute / démute", "le micro"),
        ("défun", "sourdine complète"),
        ("message", "puis « dans … »"),
        ("salon", "puis son nom"),
        ("silence / lis", "lus / pas lus"),
        ("activation", "lance le bot vocal"),
        ("viens / pars", "le bot te suit / part"),
    ]),
    ("Temps", [
        ("rappel", "puis la demande"),
        ("merci", "rappel vu"),
        ("plus tard", "dans 10 min"),
        ("timer", "puis la durée"),
        ("chronomètre", "démarre / arrête"),
        ("calendrier", "la semaine"),
        ("heure / date", "affichées 5 s"),
    ]),
    ("Iris", [
        ("stop", "arrête tout, sans « iris »"),
        ("pause", "tout désactiver"),
        ("reprise", "après la pause"),
        ("lecture", "éteint la souris"),
        ("aide", "cette page"),
        ("guide", "la documentation"),
    ]),
]

CHROME_HELP = {"retour": "page précédente", "avance": "page suivante", "suivant": "onglet suivant",
               "précédent": "onglet précédent", "onglet": "nouvel onglet", "ferme": "ferme l'onglet",
               "rouvre": "onglet rouvert", "recharge": "recharge", "favori": "favori", "haut": "haut de page",
               "bas": "bas de page", "descends": "une page plus bas", "monte": "une page plus haut",
               "agrandis": "zoom +", "réduis": "zoom −", "recherche": "barre d'adresse"}


def said_words():
    """Tous les mots cités dans l'aide (pour le test de complétude)."""
    out = set()
    for _, rows in GROUPS:
        for words, _ in rows:
            out.update(w.strip() for w in words.split("/"))
    return out


def now_block(mode, calendar_open=False, confirming=False):
    """(titre, lignes) : ce qui marche maintenant, selon le mode."""
    if mode == Mode.DISABLED:
        return "En pause", [("iris reprise", "Iris revient"), ("stop", "marche toujours")]
    if calendar_open:
        return "Calendrier ouvert, sans « iris »", [
            ("suivant / précédent", "semaine ou jour"), ("lundi … dimanche", "ce jour en grand"),
            ("aujourd'hui", "retour à aujourd'hui"), ("un jour, un mois", "« dix-huit », « mars »"),
            ("ferme / merci", "ferme le calendrier")]
    if confirming:
        return "Après la dictée, sans « iris »", [("envoie", "envoie le texte"), ("annule", "l'efface")]
    if mode == Mode.CHROME:
        return "Mode Chrome, sans « iris »", [(w, CHROME_HELP[w]) for w in CHROME_KEYS]
    return "Maintenant", [("iris + un mot", "une commande ci-dessous"), ("stop", "marche toujours, sans « iris »")]


def help_view(mode, calendar_open=False, confirming=False):
    title, rows = now_block(mode, calendar_open, confirming)
    return {"now": {"title": title, "rows": rows}, "groups": GROUPS}
