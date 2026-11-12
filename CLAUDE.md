# motionzero (« Iris »)

Contrôle de Windows par gestes (webcam, MediaPipe) et par la voix (faster-whisper), interface PySide6.
L'utilisateur n'a plus l'usage pratique de ses mains : il travaille AVEC l'appli. Une appli arrêtée ou plantée le bloque.

## Commandes
- Tests : `.venv/Scripts/python -m pytest -q` (~11 s, tout passe sans caméra ; `test_real_recording` se saute si `recordings/essai1.jsonl` manque).
- Lancer : `.venv/Scripts/python -m motionzero --voice` (en arrière-plan). Raccourci bureau « Iris » = même chose avec `pythonw`.
- Arrêter avant relance : tuer le processus python/pythonw dont la ligne de commande contient `-m motionzero` (`taskkill /F /PID`, JAMAIS `/T` : il tue aussi les applis ouvertes par Iris, Chrome compris, et le bot Discord), sinon deux instances coexistent.
- Rejouer un enregistrement : `tools/replay.py` ; enregistrer : `tools/record.py`.

## Règles
- Dès que l'appli s'arrête (STOP, croix, fin de test), la relancer tout de suite, sans demander.
- Jamais modifier l'état de `Core` (`core.py`) depuis un autre fil : passer par une queue lue dans la boucle principale.
- Chaque fonctionnalité : tester aussi les chemins d'échec (rien entendu, nom inconnu, exception d'un service). Un bug de geste → un enregistrement + un test de replay.
- Un hook `Stop` relance les tests si du Python a changé : ne pas déclarer « terminé » tant qu'ils échouent.

## Git
- Branche temporaire depuis `dev`, une seule à la fois ; fusion dans `dev` seulement après validation de l'utilisateur, puis supprimer la branche (locale + GitHub).
- Commits en français, courts. Aucune mention de Claude (pas de Co-Authored-By).
- Tout point reporté = une issue GitHub.
- Non versionnés : `models/`, `logs/`, `.venv/`, `config.json`.

## Pièges
- Whisper tourne sur GPU via les DLL `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` du venv ; il est chargé seulement avec la voix et déchargé après 10 min d'inactivité.
- Pas de touches simulées pour piloter Claude Code : voir `plan-voix-claude.md`.
- Plans existants : `plan-overlay.md`, `plan-voix-claude.md`, `motionzero.md`.
