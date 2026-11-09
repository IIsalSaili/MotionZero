# Plan : parler à Claude depuis motionzero

## Objectif
Dire « Iris, Claude, <demande> ». La demande part **à la suite de la conversation Claude du projet**, avec tout son historique. Les réponses de Claude s'affichent **à l'écran**, sans clavier, sans fenêtre à mettre au premier plan.

## Principe
On ne simule plus aucune touche. motionzero fait tout lui-même :

```
micro ─▶ Vosk (« iris », « claude », « envoie », « annule », « oui », « non »)
      └▶ enregistrement de la phrase libre ─▶ Whisper (GPU) ─▶ texte
texte ─▶ confirmation à l'écran ─▶ Claude Code en arrière-plan (reprise de la conversation)
Claude ─▶ flux d'événements ─▶ panneau de réponse à l'écran + sons
```

## Déroulé pour toi
1. **« Iris, Claude »** : son d'écoute, puis le bandeau « Je t'écoute » s'affiche.
2. Tu dis ta demande. Après environ 1,5 s de silence, l'enregistrement s'arrête.
3. Le texte compris s'affiche. **« Iris, envoie »** pour valider, **« Iris, annule »** pour abandonner.
4. Le panneau de réponse affiche l'étape en cours (« lit core.py », « modifie overlay.py »…), puis la réponse de Claude.
5. Si Claude veut faire une action risquée, « Autoriser : supprimer X ? » s'affiche. Tu réponds **« oui »** ou **« non »**.
6. Son de fin. La réponse reste affichée jusqu'à « Iris, ferme » ou jusqu'à la demande suivante.

## Quelle conversation
- **Projet :** le dernier projet utilisé. On en change en disant « Iris, projet <nom> ». Les noms viennent de la liste des dossiers que tu as déjà ouverts avec Claude, et on n'en dicte jamais le chemin. Au premier lancement : motionzero.
- **Conversation :** la plus récente du projet, ou la conversation ouverte dans VS Code. Elle est reprise à la suite. Les conversations internes (sous-agents) sont ignorées.
- **« Iris, Claude, nouvelle session »** démarre une conversation propre.
- Le dossier de stockage dépend de la casse de la lettre du disque : `c:` pour VS Code, `C:` pour le terminal. motionzero utilise donc la même écriture que VS Code. **C'est le premier point à tester.**
- Une seule demande à la fois par projet. Si tu reparles pendant que Claude travaille, l'écran affiche « Claude travaille encore ».

## Panneau de réponse à l'écran
- C'est une fenêtre séparée de la fenêtre caméra, toujours au premier plan, semi-transparente, dans un coin. Elle **ne prend jamais le focus**, pour ne pas voler les clics.
- Contenu : le projet, l'état (écoute / transcrit / en cours / terminé), l'étape en cours, puis la réponse.
- Une réponse longue se fait défiler avec le geste de défilement déjà en place.
- La forme exacte reste à décider, on la règle après le premier essai.
- En option, plus tard : lecture du résumé à voix haute par la voix de Windows. Désactivée par défaut.

## Sécurité
- Claude peut modifier librement les fichiers du projet.
- Ces actions passent par une confirmation « oui / non » : commandes système, suppressions, git push, accès réseau.
- Il y a une limite de tours par demande, pour éviter qu'une transcription mal comprise ne parte en boucle.

## Étapes
| # | Étape | Fichiers | Vérification |
|---|---|---|---|
| 0 | **Tests de faisabilité** : Claude Code accessible depuis Python, connexion avec l'abonnement Pro, reprise d'une conversation jetable (`c:` et `C:`), ce qu'affiche VS Code après la reprise | `tools/test_claude_resume.py` | la reprise répond avec le contexte de la conversation |
| 1 | Installer faster-whisper (CUDA) et claude-agent-sdk | `pyproject.toml` | import OK, Whisper sur le GPU |
| 2 | Enregistrement de la phrase libre, arrêt au silence | `voice.py` | enregistrement de test |
| 3 | Transcription Whisper, modèle chargé au premier usage, vocabulaire des projets | `transcribe.py` (nouveau) | 10 phrases test, précision et durée |
| 4 | Pont vers Claude : choix de la conversation, reprise, flux d'événements, permissions, verrou | `claude_bridge.py` (nouveau) | demande réelle sur une conversation jetable |
| 5 | Machine à états vocale : claude → transcrit → envoie/annule → en cours → oui/non → terminé ; « projet <nom> », « nouvelle session », « ferme » | `core.py`, `config.py` | tests unitaires |
| 6 | Panneau de réponse à l'écran | `response_panel.py` (nouveau), `app.py` | essai réel |
| 7 | Sons : écoute, envoyé, permission, terminé | `sounds.py` | à l'oreille |
| 8 | Nettoyage : retirer la dictée par raccourci (`dictation_keys`, `dictation_tick`, `test_dictation_key.py`, ancien test), mettre à jour le bandeau des raccourcis | `core.py`, `output.py`, `overlay.py`, `tests/` | tests verts |

On s'arrête après l'étape 0 si la reprise ou la connexion Pro ne fonctionnent pas en arrière-plan.

## Points ouverts
- Forme exacte du panneau à l'écran : à régler après le premier essai.
- Lecture à voix haute : à trancher plus tard.
- Création d'un projet à la voix : écartée pour l'instant.
