# 04 — Features à ajouter (check-up du 13/11/2026)
> Plan seul, rien n'est codé. Périmètre lu : brief commun, liste des mots (`voice.py:26-85`), raccourcis (`core.py:37-48`), greps ciblés dans `src/motionzero/`, issues #1-#34. Non couvert : lecture complète de ui.py, overlay.py, apps.py, typer.py, plans .md ; aucun test en usage réel.

## Déjà prévu (issues à citer, pas à réinventer)
- Clic sans main : #3 pédale, #25 pédale navigation, #31 expression du visage, #12 regard.
- Précision : #4 grille 3×3, #24 numéros sur liens Chrome, #26 onglet par numéro / favori.
- Retours : #9 lire la réponse de Claude, #27 / #18 bandeau, #28 volume Iris.
- Micro qui se fige : #23 (réparation existe déjà : `audio_repair.py`, `voice.py:369`).
- Discord : #6, #7. Agenda : #22. Lecture : #5.

## Déjà fait (vu dans le code)
- Copier / coller à la voix (`core.py:37`), Échap (« annule », `voice.py:37`), dictée « type » (`voice.py:52`), Alt+Tab (« tab »).
- Ouvrir n'importe quelle appli (« ouvre », #8 fermé).
- Panneau d'aide des mots (`core.py:62`).
- Caméra perdue → reconnexion auto (`camera.py:132-143`).
- Relance d'Iris si elle se fige : seulement par le bot Discord (`discord_link.py:4`).

## Propositions
| # | Feature | Pourquoi (trou constaté, preuve) | Esquisse d'implémentation (modules touchés) | Valeur H/M/B | Effort XS/S/M/L |
|---|---|---|---|---|---|
| 1 | Gardien local qui relance Iris (sans Discord) | La seule relance auto passe par le bot Discord (`discord_link.py:4`). Bot éteint = Iris plantée bloque l'utilisateur. | Petit script `tools/garde.py` (pythonw) : surveille un fichier « battement » écrit par `app.py`, relance si absent > 30 s ou processus mort ; respecte l'arrêt voulu (comme `bot.bye()`, `app.py:288`). | H | S |
| 2 | Démarrage automatique avec Windows | Aucune trace de démarrage auto (grep « startup / Run » : rien). Après un redémarrage, il faut cliquer le raccourci. | Raccourci dans le dossier Démarrage (`shell:startup`) qui lance le gardien. Créé par un outil, avec accord. | H | XS |
| 3 | « iris défais » = Ctrl+Z | Pas d'annulation d'une mauvaise action : « annule » = Échap (`voice.py:37`), aucun Ctrl+Z (grep). | Ajouter le mot au modèle et à `VOICE_HOTKEYS` (`core.py:37`). Nom à choisir sans conflit (règle « pas de régression »). Ajouter « refais » = Ctrl+Y. | H | XS |
| 4 | Sélection de texte à la voix | Copie existe, mais rien pour sélectionner (grep « sélectionne » : rien d'utile). Copier sans sélectionner ne sert à rien. | « iris tout » = Ctrl+A ; « iris sélectionne mot / ligne » = Ctrl+Maj+flèche / Maj+Fin. `core.py`, `voice.py`. | H | S |
| 5 | « iris coupe » = Ctrl+X et « iris efface » (Retour arrière ×mot) | Corriger une dictée ratée demande le clavier. | Ajouts dans `VOICE_HOTKEYS` ; « efface » = Ctrl+Retour arrière, répétable (`REPEATABLE`, `core.py:571`). | H | XS |
| 6 | Gestion des fenêtres | Seul Alt+Tab existe. Pas d'agrandir / réduire / ancrer / fermer une appli hors Chrome. | « iris agrandis / réduis / gauche / droite » = Win+Haut/Bas/Gauche/Droite, hors mode Chrome (où « agrandis » existe déjà, `core.py:47`). « iris quitte » = Alt+F4 avec confirmation. | H | S |
| 7 | Micro perdu : retour visible + re-tentative auto | La réparation existe, mais elle peut finir par « MICRO NON ROUVERT : relance Iris » (`audio_repair.py:55`) — impossible sans mains. | Si échec : relancer Iris soi-même (via le gardien n°1) et un son distinct. `audio_repair.py`, `app.py`. | H | S |
| 8 | Dictée longue et corrections | « type » écrit une phrase ; pas de « nouvelle ligne », ponctuation dite, « efface ça ». | Post-traitement dans `typer.py` : « à la ligne », « point », « virgule » ; garder la dernière dictée pour l'effacer. | M | S |
| 9 | « iris aide » contextuelle | Le panneau d'aide existe (`core.py:62`) ; à vérifier qu'il s'ouvre à la voix et filtre par mode (Chrome, calendrier). | Mot « aide » : affiche les mots du mode courant dans l'île. `core.py`, `overlay.py`. | M | XS |
| 10 | Explorateur de fichiers à la voix | Aucun mot pour dossiers / fichiers (grep « explorateur » : rien de vocal). | « iris dossier » puis nom (Whisper) : ouvre Documents, Téléchargements, Bureau ; s'appuyer sur `apps.py`. | M | M |
| 11 | Notifications Windows | Aucune gestion (grep « notification » : seulement `ask.py`). Un toast reste ou se rate. | « iris notifications » = Win+N ; « iris ferme » y ferme le panneau (Échap). | M | XS |
| 12 | Défilement / clic dans n'importe quel champ par numéros, hors Chrome | #24 ne couvre que Chrome. Les champs des applis bureau restent durs à viser. | API UI Automation (pywinauto/comtypes) : numéroter les éléments cliquables de la fenêtre active. `overlay.py` + nouveau module. | M | L |
| 13 | Mode « pause totale » vocal sûr | Si la caméra voit des gestes parasites (manger, parler), les clics partent. À vérifier si « pause » (`voice.py:43`) coupe aussi la souris tête. | Vérifier puis documenter ; sans état caché (règle). | M | XS |
| 14 | Journal des dernières actions à l'écran | Comprendre « qu'est-ce qu'Iris vient de faire ? » après une erreur. | 3 dernières actions dans l'accueil (`ui.py`), depuis les logs existants. Pas d'« iris retour » (rejeté). | B | S |

## Décisions à prendre par l'utilisateur
- Gardien local (n°1) + démarrage auto (n°2) : d'accord pour un raccourci dans Démarrage ?
- Nom des mots « défais », « coupe », « efface », « tout » : à tester avec Vosk pour les confusions (« coupe » proche de « copie » ?).
- « iris quitte » (Alt+F4) : confirmation vocale ou pas ? (confirmation = un petit état, à arbitrer avec la règle « sans état »).
- n°12 (numéros partout) : gros chantier, utile seulement si #24 plaît en Chrome.

## Note globale de couverture des besoins : 6,5/10 — Iris couvre bien lancer, cliquer, naviguer et dicter, mais l'édition de texte (sélection, annulation) et la survie sans aide (relance, démarrage auto) restent les vrais trous.
