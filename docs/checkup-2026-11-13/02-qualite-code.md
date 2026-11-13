# 02 — Qualité du code (check-up du 13/11/2026)
> Plan seul, rien n'est codé. Périmètre lu : structure de tous les fichiers de `src/motionzero/` (tailles, fonctions > 60 lignes, `except Exception`, constantes), lecture ciblée de `core.py` (Core, `voice`), `app.py` (`main`, `_loop`), `ui.py` (classes et fonctions de peinture), `sounds.py`, `voice.py` ; liste de `tests/`. Non couvert : lecture ligne à ligne de reminders.py, discord_link.py, vscode.py, apps.py, overlay.py ; contenu détaillé des tests.

## Déjà bien (à ne pas refaire)
- Core pur, sans Qt ni Windows : actions renvoyées en tuples, exécutées ailleurs (`app.py:436`). C'est ce qui rend les 405 tests rapides.
- Petits modules à une responsabilité : `filters.py` (34 l.), `power.py`, `timers.py`, `typer.py`.
- Fonctions d'actions déjà sorties de la boucle : `question_actions`, `open_actions`, `vscode_actions` (`app.py:553-762`), testables seules.
- Peinture de l'îlot déjà isolée dans `_IslandPainter` (`ui.py:938`) avec helpers purs testés (`clock_anim`, `island_text`…).
- Commentaires en français qui donnent le « pourquoi » (ex. `app.py:134`, `core.py:516`).
- Erreurs presque jamais silencieuses : 43 `except Exception`, seuls 2 font `pass` (et ce sont des fermetures de flux).

## Constats
| # | Où | Problème (preuve) | Correctif proposé | Gravité H/M/B | Effort XS/S/M/L |
|---|----|-------------------|-------------------|---|---|
| 1 | `app.py:124-551` | `main()` fait 427 lignes, avec 10 fonctions imbriquées (`face_landmarker`, `emergency`, `_loop`…). `_loop` seul fait 217 lignes (`app.py:308`). Tout partage des variables locales fermées : illisible et non testable. | Créer une classe `Engine` (fichier `engine.py`) : les variables locales deviennent des attributs, `_loop` est découpée en `_read_frame`, `_detect`, `_dispatch_actions`, `_update_ui`. `main()` ne fait plus que parser, construire, lancer. | H | L |
| 2 | `core.py:506-794` | `Core.voice()` fait 289 lignes : chaîne de `if` qui traite tour à tour confirmations (`:513-527`), calendrier (`:528-546`), stop (`:547`), puis toutes les commandes. 48 `elif` dans le fichier. L'ordre de priorité n'est lisible qu'en lisant tout. | Découper en étapes nommées appelées dans l'ordre : `_voice_confirm`, `_voice_calendar`, `_voice_stop`, `_voice_command` ; chaque étape renvoie des actions ou `None`. Puis une table `mot -> méthode` pour les commandes simples. Aucun changement de comportement : les tests existants servent de filet. | H | M |
| 3 | `core.py:100-180` | `Core.__init__` = 81 lignes, ~200 affectations `self.x =` dans le fichier, dont 40 horodatages `*_until`. L'état de Core est un sac de champs ; savoir « qu'est-ce qui est en cours ? » demande de tout lire. | Regrouper l'état en petits objets : `Confirm(kind, until)`, `Calendar(until)`, `Scroll(until)`… Commencer par les `*_until` liés (confirm, calendar, listen, voice_scroll). | M | M |
| 4 | `ui.py` (1462 l.) | Fichier fourre-tout : 9 classes (STOP, œil, réparer, aperçu, panneau conso, overlay, îlot…) + ~20 fonctions de géométrie. L'îlot (`ui.py:700-1462`) fait la moitié du fichier ; calendrier dessiné en 3 méthodes (`:1183-1355`). | Couper en `ui/buttons.py` (StopButton, EyeButton, RepairButton : `:512-706`), `ui/island.py` (`:708-1462`), `ui/calendar_paint.py`, `ui/windows.py` (Preview, Conso, Glass). Simple déplacement, imports à corriger. | M | S |
| 5 | `app.py:438-454` | Actions = tuples non typés (`a[0] == "mode"`, `("cal", word)`), comparées par chaîne dans 7 fonctions différentes. Une faute de frappe passe sans erreur. | Constantes nommées pour les types d'actions (ou petit `Enum`) dans `core.py`, utilisées partout. Pas besoin de dataclasses. | M | S |
| 6 | `overlay.py:64` (121 l.), `ui.py:63` `paintEvent` (99 l.), `voice.py:280` `_step` (64 l.) | Autres fonctions longues. | Découper seulement si on y retouche (gain moindre). | B | S |
| 7 | `core.py:35-85` | Tables de vocabulaire (VOICE_HOTKEYS, CHROME_KEYS, labels, ALIASES, OPEN_STOP…) mêlées à la logique, ~50 lignes. Libellés affichés dispersés entre ces tables et des chaînes en dur (`"CALENDRIER FERME"` `core.py:540`, `"TEXTE ENVOYE"` `:518`). | Sortir tables et libellés dans `vocab.py`. Aide aussi à vérifier les conflits de mots (règle « pas de régression d'usage »). | M | S |
| 8 | `sounds.py:179`, `voice.py:377` | Deux `except Exception: pass` à la fermeture du flux micro/son. Acceptable, mais un micro qui se fige (#23) laisserait zéro trace. | Remplacer par `log.debug(..., exc_info=True)`. | B | XS |
| 9 | `stats.py:93-184` | 9 `except Exception` en 90 lignes (à vérifier : renvoient-ils tous une valeur par défaut sans log ?). | Un seul helper `_safe(fn, default)` qui logge une fois. | B | XS |
| 10 | tests (`test_voice.py`, `test_engine.py`…) | Les tests appellent des méthodes privées : `._step(` ×6, `._transcribe(` ×4, `._open_spoken(` ×4, `._maybe_launch(` ×4, `core._gain` ×3, `.__new__(` ×4. Ils figent l'implémentation : un découpage (constats 1-3) les cassera sans bug réel. | Avant de découper, réécrire ces tests via l'API publique (`core.voice()`, `core.update()`, replay). `__new__` = objet construit sans `__init__` : remplacer par une petite fabrique de test. | M | S |
| 11 | `tests/` | Pas de `conftest.py` partagé (à vérifier) ; `synth.py` sert d'outil commun mais n'a pas de nom de test. Aucun test pour `ui.py` hors île (`test_island.py`). | Ajouter `conftest.py` avec fabriques `make_core(cfg)` ; garder `synth.py` en `tests/helpers/`. | B | S |
| 12 | Nommage | Mélange français/anglais sans règle : `voice`, `confirming`, `release_all` vs `cal_close`, `rappel_ok`, `type_erase`, `ferme-micro` (`voice.py:379`). | Règle simple à écrire dans CLAUDE.md : code en anglais, mots dits et textes affichés en français. Renommer au fil des retouches, pas en masse. | B | XS (règle) |

## Décisions à prendre par l'utilisateur
- Faire le gros découpage `app.py` → `Engine` (constat 1, > 1 jour) maintenant, ou seulement au prochain gros ajout ? Il touche le cœur dont tu dépends : à faire sur une branche, avec replay réel avant fusion.
- Ordre conseillé : 10 (tests sur l'API publique) → 4 (ui.py, simple déplacement) → 2 (voice) → 1 (Engine).
- Langue du code : anglais pour les noms, français pour les mots et textes ? (constat 12)
- Ouvrir une issue par constat retenu (règle du projet).

## Note globale du périmètre : 6/10, petits modules propres et Core bien testable, mais trois fonctions géantes (`main`, `_loop`, `Core.voice`) concentrent la logique et rendent la relecture difficile.
