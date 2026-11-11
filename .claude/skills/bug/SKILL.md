---
name: bug
description: Corriger un bug de motionzero en le reproduisant d'abord par un test qui échoue. Déclencheurs : /bug, « il y a un bug », « ça ne marche pas », geste ou commande vocale mal reconnu.
---

1. Comprendre le symptôme (questions en texte si besoin, jamais de choix à cliquer). Lire `logs/` récents.
2. Reproduire par un test qui ÉCHOUE avant toute correction :
   - geste : utiliser un enregistrement de `recordings/` (ou en demander un via `tools/record.py`) et un test dans le style de `tests/test_replay.py` / `test_real_recording.py` ;
   - voix / commande : test unitaire dans le style de `tests/test_voice.py` ;
   - plantage entre fils : vérifier qu'aucun fil ne touche l'état de `Core` hors de la boucle principale.
   Montrer la sortie du test rouge.
3. Corriger au plus simple, puis montrer la sortie du test vert et de la suite complète.
4. Ajouter un test pour le chemin d'échec voisin évident.
5. Relancer motionzero (skill relancer) et dire à l'utilisateur quoi essayer, en une phrase.
