# Check-up du 13/11/2026 — synthèse

> Plan seul, rien n'est codé. 5 agents : 01 optimisation, 02 qualité du code, 03 pertinence des features, 04 features à ajouter, 05 implémentation feature par feature. Les rapports détaillés sont dans ce dossier.
> Point de départ : 405 tests passent (10,5 s). J'ai revérifié moi-même les constats graves (marqués ✔). Il n'y a pas eu de relecteur final, pour économiser le quota.

## 1. Verdict

L'appli est saine et déjà bien optimisée. Ses deux vrais points faibles sont ailleurs :
- **La reprise après un plantage** : Iris ne se relance pas seule sans le bot Discord, et ne démarre pas avec Windows.
- **Deux gros blocs de code difficiles à relire** : `main()` dans `app.py`, et `Core.voice()` dans `core.py`.

Côté usage, l'aide affichée est très en retard sur les commandes réelles, et il manque des gestes de base pour corriger du texte : annuler, sélectionner, couper.

| Agent | Note |
|---|---|
| 01 Optimisation | 8/10 |
| 02 Qualité du code | 6/10 |
| 03 Pertinence des features | 7/10 |
| 04 Couverture des besoins | 6,5/10 |
| 05 Implémentation | 7,5/10 |

## 2. Ce qui est bien

- Perf : boucle ralentie sans main, MediaPipe arrêté en pause, Whisper déchargé après 10 min, overlay qui ne repeint que ce qui change. [01]
- Bonnes approches techniques : filtre One Euro sur la tête, grammaire Vosk restreinte avec une seconde vérification, `vad_filter` de Whisper, volume par l'API Windows, `SendInput`, rappels écrits de façon sûre (atomique). [05]
- Les fils ne touchent pas `Core` : le bot Discord passe par une inbox. [02, 05]

## 3. Ce qui ne va pas

### Bloquants (le jour où ça arrive, l'utilisateur est coincé)

| # | Constat | Source |
|---|---|---|
| B1 ✔ | Sans le bot Discord, rien ne relance Iris après un plantage. Iris ne démarre pas non plus avec Windows (`discord_link.py:3`, grep « startup » vide). | [04 n°1-2] |
| B2 ✔ | `config.json` est réécrit directement (`config.py:170`). Un plantage pendant l'écriture remet tous les réglages par défaut, sans rien dire (`config.py:162`). | [05 n°1] |
| B3 | Micro non réparé : le message dit « relance Iris » (`audio_repair.py:55`). L'utilisateur ne peut pas le faire sans ses mains. | [04 n°7] |

### Majeurs

| # | Constat | Source |
|---|---|---|
| M1 ✔ | L'aide vocale liste 20 mots sur plus de 60 (`overlay.py:204-225`). Il manque rappel, timer, calendrier, volume, Chrome, tête… L'aide souris dit « Main absente 2 s > LECTURE » (`overlay.py:43`), ce qui n'est plus vrai. | [03 C1, 04 n°9] |
| M2 | Pas de Ctrl+Z, ni de sélection de texte, ni de Ctrl+X, ni de « efface le mot ». « copie » existe mais ne sert à rien sans sélection. | [04 n°3-5] |
| M3 | Fenêtres : seul Alt+Tab existe. Rien pour agrandir, réduire, ancrer ou fermer une appli hors Chrome. | [04 n°6] |
| M4 | `app.py` : `main()` fait 427 lignes, dont `_loop` 217. `core.py` : `Core.voice()` fait 289 lignes de `if/elif`. Les deux sont illisibles et `_loop` ne se teste pas seul. | [02 n°1-2] |
| M5 | Les tests appellent des méthodes privées (`_step`, `_transcribe`…). Tout découpage de M4 les casserait sans vrai bug. Il faut les réécrire **avant** M4. | [02 n°10] |
| M6 ✔ | « iris ferme » : le libellé « dis le nom de l'appli » est aussitôt écrasé (`core.py:711-712`). Ensuite, les commandes sont ignorées pendant l'attente d'un nom. | [03 C3] |
| M7 | En mode Chrome, 17 mots courants marchent sans « iris » (« retour », « bas », « ferme »…). Risque de déclenchement pendant un appel. Non mesuré. | [03 C2] |
| M8 | VS Code est mis au premier plan par un Alt simulé (`keybd_event`, déprécié), puis une attente fixe (`vscode.py:44-50`). | [05 n°2] |
| M9 ✔ | La réponse de Haiku pour les rappels est lue avec la regex gourmande `\{.*\}` (`reminders.py:150`). | [05 n°3] |
| M10 | La caméra décode et copie 30 images/s alors que la détection n'en prend que 20, et 5 sans main (`camera.py:118-122`). La loupe capture l'écran 20 fois/s même quand le curseur ne bouge pas (`ui.py:438`). | [01 n°1, 3] |

### Mineurs (le détail est dans les rapports)

- Calendrier recalculé 20 fois/s ; état envoyé à l'UI même quand rien ne change. [01 n°4-5]
- `ui.py` (1462 lignes) à couper en 4 fichiers. Actions transmises en tuples de chaînes. Environ 40 champs `*_until` dans `Core`. [02 n°3-5]
- Erreurs avalées sans log, à la fermeture du micro (utile pour #23) et dans `stats.py`. [02 n°8-9]
- `apps.py` lance PowerShell à chaque fois. `leveldb_mini` recopie toute la base Discord. [05 n°4-5]
- Mélange français/anglais dans les noms. [02 n°12]

## 4. Arbitrages entre agents

- **Refonte de `core.py`/`app.py` (02) contre risque de régression** : on la fait par petits pas, après avoir réécrit les tests (M5). Pas de réécriture d'un bloc.
- **Clic par la main (03 C7)** : l'agent 03 le voit comme un doublon du « clic » vocal. Il n'est pas retiré : seul l'utilisateur sait s'il s'en sert (règle « ne pas retirer d'usage »).
- **Mots Chrome sans « iris » (03 C2)** : on ne change rien avant d'avoir mesuré en usage réel. C'était un choix validé dans `plan-navigation-chrome.md`.
- **VAD Silero et UI Automation (05, 04 n°12)** : utiles comme briques, mais coûteux. Ils passent après le reste.

## 5. Ordre de correction en lots

| Lot | Contenu | Effort |
|---|---|---|
| 0 (sans code) | Mettre à jour l'aide affichée (M1). Écrire la règle de nommage dans CLAUDE.md. | XS |
| 1 Sûreté | Écriture sûre de `config.json` (B2). Gardien local + démarrage avec Windows, avec ton accord (B1). Auto-relance quand le micro ne se répare pas (B3). | S-M |
| 2 Texte et fenêtres | « défais », sélection, « coupe », « efface », agrandir/réduire/ancrer (M2, M3). Chaque mot testé contre Vosk pour éviter les confusions. | S |
| 3 Petits bugs | Libellé de « ferme » (M6), JSON strict pour les rappels (M9), focus VS Code par `SendInput` + vérification (M8). | S |
| 4 Perf | 20 images/s pour la caméra, loupe seulement quand le curseur bouge, calendrier en cache (M10 + mineurs). | S |
| 5 Lisibilité | Tests sur le comportement (M5), puis `Engine` à la place de `main()`, `Core.voice()` en étapes avec une table de mots, `ui.py` découpé (M4). | L |
| 6 Plus tard | « iris aide » selon le mode, dictée avec ponctuation, notifications, dossiers, VAD, UI Automation. | M-L |

## 6. Décisions à trancher par l'utilisateur

1. **D1** Démarrage automatique avec Windows et gardien local : d'accord ? Recommandé : oui.
2. **D2** Mots Chrome sans « iris » : on les mesure pendant un vrai appel avant de décider ? Recommandé : oui.
3. **D3** Clic par la main (main fermée puis rouverte) : tu t'en sers ? Sinon, on le désactive par défaut, sans le supprimer.
4. **D4** Caméra : passer à 20 images/s, ou lire une image seulement quand la boucle en a besoin ? Recommandé : 20 images/s, c'est le plus simple.
5. **D5** Noms des nouveaux mots : « défais » (Ctrl+Z), « coupe » (risque de confusion avec « copie »), « efface », « tout ».
