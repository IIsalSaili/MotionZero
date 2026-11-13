# 03 — Pertinence des features (check-up du 13/11/2026)
> Plan seul, rien n'est codé. Périmètre lu : `core.py` (modes, `voice()` en entier), `voice.py` (liste des mots, alias, seuils), `overlay.py` (aides affichées), `calendar_view.py` (mots), en-têtes de `stats.py`, `app.py` (branchements), `git log --oneline -80`.
> Non couvert : détail de `ui.py`, `reminders.py`, `timers.py`, `volume.py`, `vscode.py`, `discord_link.py`, `sounds.py`, `apps.py` (lus seulement via leurs appels dans `core.py`). Aucun test en usage réel.

## Inventaire

| Feature | Où | Verdict |
|---|---|---|
| Mode neutre (main inactive, voix seule) | `core.py:28` | utile |
| Mode lecture (paume au bord = page, haut/bas = défile) | `core.py:328`, `overlay.py:22` | utile, doublon partiel (C4) |
| Souris (outil, main ou tête) + « clic / double / menu » sans « iris » | `core.py:584`, `core.py:750` | utile |
| Souris à la tête, « iris centre » | `core.py:753`, commits ff016af, 2322829 | utile (cœur du besoin) |
| Clic par la main (main fermée puis rouverte) | `core.py:333`, réglage `hand_click_enabled` | à revoir (C7) |
| « défile » en bascule + jauge | `core.py:652-660`, d060dcc | utile, vérifs en cours (#32) |
| Mode Chrome (17 mots sans « iris ») | `core.py:42-53`, `core.py:603` | utile, fragile (C2) |
| Touches : entrée, espace/space, annule, copie, colle, tab, skip/back répétables | `core.py:37`, `core.py:61` | utile |
| « claude » (micro VS Code) + envoie/annule | `core.py:667`, `core.py:521` | utile |
| « question » (réponse dans l'île) | `core.py:688` | utile, distinct de « claude » |
| « type » (dictée au curseur) + « recherche » en Chrome | `core.py:699`, `core.py:607` | utile |
| « ouvre » / « ferme » + nom d'appli | `core.py:693`, `core.py:705` | utile, « ferme » surchargé (C3) |
| Rappels, « merci » / « ok », « plus tard » | `core.py:735-740` | utile |
| Chronomètre, timer | `core.py:717-729` | utile |
| Calendrier (ses mots sans « iris » quand il est ouvert) | `core.py:531-548`, `calendar_view.py:28` | utile |
| Heure / date | `core.py:733` | utile |
| Volume | `core.py:741-749` | utile |
| Discord : mute/muet, démute, défun/sourdine, message, salon, silence, lis | `core.py:767-787` | utile |
| Bot vocal : activation, viens, pars | `core.py:758-766` | à revoir (C6) |
| Apps : discord, chrome, studio, accueil | `core.py:776` | utile |
| « pause » (tout coupé, « iris » réveille) | `core.py:788` | utile |
| « réveil / wake » (écran rallumé) | `core.py:714` | utile depuis le retrait du maintien éveillé (6b56a45) |
| « stop » (toujours écouté) | `core.py:549` | essentiel |
| Aides affichées (fenêtre accueil) | `overlay.py:15-45`, `overlay.py:204-225` | **obsolète** (C1) |
| Conso (CPU/GPU) | `stats.py`, `app.py:238` | utile pour le suivi, RAS |
| Boutons « réparer le son », œil, STOP | 72b90df, `ui.py:505-579` | utile |

## Déjà bien (à ne pas refaire)
- Une seule commande par « iris » : plus de mot de conversation exécuté par erreur (`core.py:625-627`).
- Les mots Chrome ne sont écoutés qu'en mode Chrome (grammaire par mode, `voice.py:122`, `core.py:631`).
- « stop » toujours prioritaire et adapté au contexte : défilement, souris, mode (`core.py:549-563`).
- « lâche » toujours écouté quand le bouton est tenu (`core.py:565`).
- Un mot dit seul exige une confiance plus haute, 0,8 (`voice.py:163`).
- Message clair quand un mot est ignoré : « dis IRIS avant », « seulement en mode Chrome » (`core.py:620`, `core.py:633`).
- Alias pour les mots mal reconnus au lieu d'en retirer (`voice.py:93`).

## Constats

| # | Où | Problème (preuve) | Correctif proposé | Gravité | Effort |
|---|---|---|---|---|---|
| C1 | `overlay.py:204-225`, `overlay.py:15-45` | L'aide vocale affichée liste 20 mots. Il en existe plus de 60 (`voice.py:25-82`, 17 mots Chrome, mots du calendrier). Absents : rappel, timer, chronomètre, calendrier, heure, volume, question, tête/main/centre, Discord, Chrome… L'aide souris dit « Main absente 2 s > LECTURE » (`overlay.py:43`) alors que la souris n'est plus un mode (1084ca2) : à vérifier. C'est le seul moyen de découvrir les commandes. | Générer l'aide depuis `VOICE_LABELS` / `CHROME_LABELS` (une seule source), par thème, mots du mode en cours en premier. | H | S |
| C2 | `core.py:577-612`, `core.py:42-48` | En mode Chrome, 17 mots + skip/back/espace/clic/double marchent **sans « iris »**. « retour », « bas », « haut », « monte », « suivant », « ferme » sont des mots courants. En appel Discord avec Chrome devant, une phrase courte finie par un de ces mots peut agir (« ferme » ferme l'onglet). Garde-fous : mot seul + confiance 0,8. Pas d'enregistrement de conversation réelle trouvé : à vérifier. | Mesurer d'abord : log des mots Chrome exécutés pendant un appel. Si faux déclenchements : décision D1. | H | S |
| C3 | `core.py:705-713` | « iris ferme » fait deux choses : retire la réponse ET attend un nom d'appli. Pendant l'attente, les commandes sont ignorées (`core.py:511`). Le libellé est écrit deux fois, le premier est perdu (`core.py:711-712`) : l'écran dit « FERME » et pas « dis le nom de l'appli ». Sens différent en Chrome (onglet). Va-et-vient dans l'historique : 2e9ed11 puis adb1fad ; #34. | Supprimer la 2e ligne du libellé. Le fond : décision D2. | M | XS |
| C4 | `overlay.py:26`, `core.py:652`, `core.py:46` | Trois façons de défiler : lecture (paume haut/bas), « iris défile » (jauge), Chrome « monte / descends / haut / bas ». Charge mentale. Vérifs d'usage réel prévues (#32). | Après #32, mettre en avant celui qui sert dans l'aide (C1). Aucun retrait sans accord. | M | XS |
| C5 | `core.py:513-529`, `core.py:674-681` | « envoie » et « annule » changent de sens selon le contexte (Entrée / envoi à Claude / valide un rappel ; Échap / vide Claude / efface la dictée / refuse un rappel), parfois sans « iris » pendant quelques secondes. Rien n'affiche cette fenêtre, sauf pour le rappel (51ca77f). | Afficher « envoie / annule » avec compte à rebours après dictée et Claude, comme pour le rappel. | M | S |
| C6 | `core.py:758-766` | Bot vocal : « activation » sert seulement à précharger pour que « viens » soit rapide. Un mot de plus pour un détail technique. | « viens » fait l'activation si besoin (« activation » reste). | B | S |
| C7 | `core.py:333-340` | Clic par la main : absent de l'aide, doublon du « clic » vocal. Usage réel inconnu : à vérifier. | Demander à l'utilisateur (D4). | B | XS |
| C8 | `voice.py:25-82` | Nombreux alias (mute/muet, défun/sourdine, espace/space, réveil/wake, merci/ok/okay, envoie/envoyé). Bon pour la reconnaissance ; chaque mot élargit un peu la grammaire. Pas gênant aujourd'hui. | Rien ; surveiller les mots mal pris dans les logs. | B | XS |

## Décisions à prendre par l'utilisateur
- **D1** (C2) : si des faux déclenchements en mode Chrome sont confirmés, quels mots garder sans « iris » ? Les plus risqués : « ferme », « retour », « bas ». Retirer l'usage sans « iris » = retirer un usage existant : à toi de décider.
- **D2** (C3) : « iris ferme » doit-il toujours attendre un nom d'appli ? « merci / ok » retire déjà l'affichage du haut.
- **D3** (C4) : après #32, quel défilement préfères-tu ? Les autres restent, l'aide mettra celui-là en avant.
- **D4** (C7) : te sers-tu du clic par la main ?

## Note globale du périmètre : 7/10 — features utiles et pensées pour un usage mains libres, mais l'aide affichée ne couvre qu'un tiers des commandes et le mode Chrome sans « iris » reste à surveiller.
