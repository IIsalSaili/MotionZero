"""« iris alt-tab » (#75) : la fenêtre d'avant (= la 2e dans l'ordre d'Alt+Tab), puis la liste des fenêtres
suivantes, numérotées, affichée en haut. Pendant ALTTAB_S secondes, « deux » … « six » (sans « iris ») vont à
la fenêtre de ce numéro ; « iris alt-tab trois » d'un trait fait pareil. Règle unique : le numéro N = la Nième
fenêtre dans l'ordre d'Alt+Tab au moment où on le dit, c'est-à-dire celui de la liste affichée. Pur : testable."""

ALTTAB_NUMBERS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6}
ALTTAB_S = 8.0          # liste affichée, chiffres écoutés sans « iris »
ALTTAB_MAX = 6          # fenêtres lues (la 1re est celle de devant)
SHORT_NAMES = {"Google Chrome": "Chrome", "Visual Studio Code": "VS Code", "Explorateur de fichiers": "Explorateur"}


def _cut(s, n):
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def window_labels(titles, maxlen=14):
    """Titres de fenêtres -> noms courts : le nom de l'appli (fin du titre après « - ») ; deux fenêtres de la
    même appli : le début du titre (la page, le fichier) pour les distinguer."""
    apps = []
    for title in titles:
        parts = [p.strip() for p in title.split(" - ") if p.strip()]
        name = parts[-1] if parts else title.strip()
        apps.append(SHORT_NAMES.get(name, name))
    out = []
    for title, app in zip(titles, apps):
        if apps.count(app) > 1:
            out.append(_cut(title.split(" - ")[0].strip() or app, maxlen))
        else:
            out.append(_cut(app, maxlen))
    return out


def list_text(titles):
    """Texte de l'îlot : « 2 Chrome   3 Discord   4 VS Code » ; la 1re (celle de devant) n'y est pas.
    None s'il n'y a pas d'autre fenêtre."""
    labels = window_labels(titles)
    return "   ".join(f"{i} {lab}" for i, lab in enumerate(labels, 1) if 2 <= i <= ALTTAB_MAX) or None


def number_of(word):
    """« alt-tab » -> 2, « alt-tab trois » -> 3, « trois » -> 3 ; autre chose -> None."""
    if word == "alt-tab":
        return 2
    if word.startswith("alt-tab "):
        word = word[len("alt-tab "):]
    return ALTTAB_NUMBERS.get(word)
