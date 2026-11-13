# 01 — Optimisation (check-up du 13/11/2026)
> Plan seul, rien n'est codé. Périmètre lu : `app.py` (boucle moteur 300-520), `camera.py`, `voice.py` (écoute), `ask.py` (Whisper), `ui.py` (set_state, loupe, aperçu), `reminders.py` (fichier, events/state), `calendar_view.py` (view), `stats.py` (run_sampler), `vscode.py` (chrome_in_front), `tests/test_perf.py`.
> Non couvert : `core.py` en détail, `gestures.py`, `hand.py`, `head.py`, `overlay.py` (render), `discord_link.py`, `apps.py`, `sounds.py`. Aucune mesure lancée (lecture seule) : tous les gains sont **supposés** sauf mention.

## Déjà bien (à ne pas refaire)
- Détection plafonnée à 20 i/s, 5 i/s sans main ou en pause (`app.py:37-38`, `app.py:117-121`), testée (`tests/test_perf.py:12`).
- En pause, MediaPipe ne tourne pas (`app.py:355`). Souris à la tête : seul le visage est détecté (`app.py:333`).
- Aperçu caméra dessiné seulement si la fenêtre est visible (`app.py:466`).
- Overlay : repeint seulement les zones changées (curseur, fantôme, jauge, île) (`ui.py:340-369`) ; timer d'animation 16 ms actif seulement pendant une animation (`ui.py:310-354`).
- Reconnaissance libre Vosk endormie dans le silence (`tests/test_perf.py:50`) ; Whisper déchargé après 10 min (`ask.py:123-131`), chargement sous verrou (`ask.py:105`).
- Panneau de consommation : aucune mesure tant qu'il est caché (`stats.py:174-186`).
- Caméra : attente sur condition, pas de boucle active (`camera.py:154-161`, `camera.py:135`).
- Rappels : échéances vérifiées 1 fois/s, pas à chaque image (`reminders.py:416`, `TICK_S` `reminders.py:317`) ; écriture atomique (`reminders.py:243-250`).

## Constats
| # | Où | Problème (preuve) | Correctif proposé | Gravité H/M/B | Effort XS/S/M/L |
|---|----|-------------------|-------------------|---------------|-----------------|
| 1 | `camera.py:118-122`, `camera.py:66` | La caméra lit, décode le MJPG, vérifie (`frame_is_valid`) et **copie** chaque image à 30 i/s, alors que la détection n'en prend que 20, voire 5 sans main. Jusqu'à 25 images/s décodées et copiées pour rien. | Option A : demander `fps=20` (= `DETECT_MAX_FPS`). Option B : `cap.grab()` à chaque tour, `retrieve()` + vérif + copie seulement quand le moteur en a besoin (drapeau « veut une image »). Mesurer le CPU avant/après (panneau conso). | M | S |
| 2 | `app.py:331`, `app.py:337` / `app.py:358` | Deux passes pleine image par détection : `cv2.flip` puis `cv2.cvtColor` (2 allocations 640×480×3). | Gain faible, supposé (< 1 ms). À ne faire que si une mesure montre un besoin. | B | XS |
| 3 | `ui.py:438-446` | La loupe fait `grabWindow` de l'écran à chaque état reçu (jusqu'à 20 fois/s) dès que le curseur est affiché, même si le curseur n'a pas bougé. | Ne recapturer que si le curseur a bougé de plus de 1-2 px **ou** toutes les 200 ms (le contenu sous le curseur peut changer). Gain supposé, à mesurer. | M | S |
| 4 | `app.py:498`, `reminders.py:549`, `calendar_view.py:147-170` | Calendrier ouvert : la vue (mois entier + 7 jours, `day_cards` pour chaque jour) est recalculée à chaque état, 20 fois/s, alors qu'elle ne change qu'à une commande ou au changement de jour. | Mémoriser le résultat ; invalider à `add`/`cancel`/`tick`/changement de semaine ou de date. | B | S |
| 5 | `app.py:478-500` | `bridge.state.emit` envoie un gros dict au fil Qt à chaque détection (20/s), même quand rien n'a changé (main absente, curseur fixe). Coût Python + signal croisé de fil ; l'overlay filtre ensuite. | Envoyer seulement si le dict diffère du précédent (comparaison simple), ou au moins 1 fois/s. Attention : `toast_age` et `ok_flash` changent avec le temps → les garder hors comparaison ou laisser l'île calculer l'âge. Gain supposé. | B | S |
| 6 | `app.py:376` | Caméra muette : `last_view.copy() // 3` alloue deux images pleine taille à chaque tour (≈ 20/s) pendant toute la panne. | Calculer l'image assombrie une fois (à l'entrée en panne) et la réutiliser. | B | XS |
| 7 | `ask.py:100-101`, `ask.py:123-125` | Le fil « whisper-veille » sonde toutes les 30 s pour toujours. Un seul appel à `preload()` (`app.py:184`) donc pas de fuite aujourd'hui ; mais un 2e appel créerait un 2e fil. | Garde « déjà lancé » dans `preload`. Le sondage 30 s est acceptable (coût nul). | B | XS |
| 8 | `app.py:66` (watch_engine), `stats.py:186` | Sondages périodiques (garde de blocage, mesures) : légers et justifiés. | Rien à faire. | — | — |
| 9 | `voice.py:283`, `voice.py:325-338` | `json.loads` sur `PartialResult()` à chaque bloc de 30 ms (≈ 33/s) côté grammaire. Coût faible (petites chaînes). | Rien, sauf si une mesure le montre. À vérifier avec un profil. | B | — |
| 10 | `tests/test_perf.py` | Les tests vérifient les règles (ralenti, sommeil, déchargement) mais aucun ne mesure un coût réel (temps par image, images décodées/s). Une régression de perf passerait inaperçue. | Ajouter un banc hors tests (`tools/`) qui rejoue `recordings/*.jsonl` et affiche le temps moyen de `core.step` et du rendu ; pas de seuil dur en CI (machines variables). | B | S |

## Décisions à prendre par l'utilisateur
- Constat 1 : caméra à 20 i/s (simple, peut un peu changer la fluidité de l'aperçu) ou `grab/retrieve` à la demande (plus de code, garde 30 i/s) ?
- Constat 3 : une loupe rafraîchie 5 fois/s quand le curseur est immobile te gêne-t-elle (vidéo sous le curseur) ?
- Faut-il d'abord mesurer (panneau conso, 5 min main présente / absente) avant tout correctif ? Recommandé.

## Note globale du périmètre : 8/10, le gros du travail de perf est déjà fait (ralenti sans main, pause sans MediaPipe, Whisper déchargé, repeints ciblés) ; il reste surtout la caméra qui décode plus d'images que nécessaire.
