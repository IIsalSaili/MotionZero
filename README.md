# Iris (motionzero)

Piloter Windows sans les mains, par gestes devant la webcam et par la voix.

<!-- Vidéo de démonstration : docs/demo.mp4 (à venir) -->

## Ce que fait Iris

- **Pointer et cliquer** : la main ou la tête, suivie à la webcam (MediaPipe, OpenCV), déplace la souris.
- **Commandes vocales** : « iris » suivi d'un mot (ouvrir une appli, défiler, cliquer, régler le volume, timer...). Mot de réveil hors ligne (Vosk).
- **Dictée** : transcription locale sur carte graphique (faster-whisper, CUDA), écrite dans le champ actif.
- **Instruction libre** : une phrase en langage naturel, traduite en plan d'actions par un LLM local (Ollama). Rien ne s'exécute sans confirmation orale.
- **Discord à la voix** : un bot compagnon lit les messages à voix haute, écrit et gère le serveur à la voix.
- **Surimpression** : un îlot discret affiche l'état d'Iris (écoute, mode actif).
- **Toujours disponible** : un gardien relance Iris si elle plante ou se fige.

Une version Android (IrisAPK) pilote aussi le téléphone à la voix.

## Prérequis

En cours de développement. Il faut :

- Windows 10 ou 11, webcam, micro ;
- carte graphique NVIDIA (pour Whisper) ;
- Python 3.12+ ;
- [Ollama](https://ollama.com) pour l'instruction libre (facultatif).

La procédure d'installation complète est en préparation.

## Lancer

```
python -m venv .venv
.venv/Scripts/pip install -e .
.venv/Scripts/python -m motionzero --voice
```

Tests (sans caméra) : `.venv/Scripts/python -m pytest -q`.

## Documentation

Le [guide](docs/guide/README.md) détaille l'utilisation, toutes les commandes vocales, l'architecture et le dépannage.

## Licence

[MIT](LICENSE)
