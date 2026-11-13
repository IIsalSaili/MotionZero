# 05 — Implémentation feature par feature (check-up du 13/11/2026)

> Ceci est un plan seulement : rien n'a été codé.
> Ce que j'ai lu : voice.py (230-330), ask.py (120-170), head.py, filters.py, apps.py (30-80), volume.py (95-125), vscode.py (40-50, plus un grep), leveldb_mini.py (110-130), config.py (160-172), camera.py (les signatures), sounds.py (l'en-tête), power.py, reminders.py (140-160), app.py (495-505). J'ai aussi fait un grep des techniques utilisées sur tout `src/motionzero`.
> Ce que je n'ai pas lu en détail : gestures.py, poses.py, hand.py (sauf le grep), core.py, ui.py, overlay.py, timers.py, calendar_view.py, discord_link.py (sauf les imports), stats.py, typer.py. Je n'ai pas non plus lu les plans et les tests. Sur ces fichiers, mon avis est « à vérifier ».

## Déjà bien (à ne pas refaire)
- **Pointeur** : il est lissé par un vrai filtre One Euro (filters.py:1-34). Ce filtre est appliqué à l'orientation de la tête calculée par MediaPipe (head.py:93-94). Le sens de chaque axe est confirmé par vote (head.py:73-84).
- **Vosk** : la grammaire est restreinte (voice.py:245). Elle change selon le mode, et seulement entre deux phrases (voice.py:309-314). Un second moteur sans grammaire vérifie les mots entendus (voice.py:247). Ce moteur ne tourne que pendant que quelqu'un parle, avec le son d'avant gardé en mémoire (voice.py:320-331).
- **Whisper** : il utilise `vad_filter=True` (ask.py:139). Un verrou empêche deux transcriptions en même temps sur la carte graphique (ask.py:137). Le modèle est déchargé quand il ne sert plus (ask.py:122-130).
- **Volume** : il passe par l'API native Core Audio, via pycaw, avec COM initialisé dans chaque fil (volume.py:84-125).
- **Entrées** : souris et clavier passent par `SendInput` (output.py:54-61). Un chien de garde relâche tout ce qui reste appuyé.
- **Caméra** : un fil dédié et une `Condition` (camera.py:153-160). Une image abîmée est rejetée (camera.py:24), et la caméra se reconnecte toute seule.
- **Rappels** : l'enregistrement est sûr. Le fichier est écrit à côté puis remplacé (`os.replace`). Un fichier abîmé est mis de côté (reminders.py:233-249).
- **Écran** : `SetThreadExecutionState` est appelé une seule fois, sans réglage permanent (power.py:17).

## Par feature

**Détection « iris » (voice.py)**
- Approche actuelle : un seuil d'énergie (RMS) qui s'adapte au bruit de fond (voice.py:291-299). La grammaire Vosk est restreinte et vérifiée par le moteur libre.
- Alternative : remplacer le seuil RMS par un vrai détecteur de voix (VAD). Silero est disponible sous forme ONNX, et webrtcvad aussi. Il servirait à réveiller le moteur libre et à mesurer `last_speech_t`.
- Gain : moins de réveils sur les bruits (clavier, musique Discord).
- Risque : une dépendance de plus. Un réglage est à refaire en usage réel.

**Dictée / question / claude (ask.py)**
- Approche actuelle : capture des blocs Vosk, puis Whisper transcrit le tout. Ensuite, `claude -p` est lancé en sous-processus avec `subprocess.run` et un délai maximum (ask.py:54).
- Alternative : aucune meilleure ne s'impose. Deux petites améliorations possibles :
  - Passer `initial_prompt` à Whisper avec le vocabulaire courant (Iris, noms d'applis). La transcription serait plus juste.
  - Le déchargeur vérifie toutes les 30 s (ask.py:125). Un `threading.Timer` réarmé à chaque usage ferait la même chose.
- Risque : faible.

**Gestes / poses / main (gestures.py, poses.py, hand.py)**
- Approche actuelle : un suivi de main avec appariement par distance, et une vitesse lissée par moyenne glissante (EMA) (hand.py:59-79).
- Alternative : pour la vitesse, utiliser la dérivée déjà calculée par le One Euro au lieu d'une moyenne glissante séparée. Le reste est à vérifier (non lu).
- Gain : un seul lissage cohérent.
- Risque : les seuils de geste sont à recaler, et il faut repasser les tests de replay.

**Souris à la tête (head.py)**
- Approche actuelle : la matrice MediaPipe est convertie en angles, puis lissée par One Euro, puis filtrée par une zone morte. Les gains sont fixes (scale=1.4, scale_y=2.0).
- Alternative : un gain qui dépend de la vitesse (courbe d'accélération, comme le pointeur Windows). Lent = précis, rapide = grands déplacements. C'est déjà prévu dans #17 (réglages souris).
- Point fragile : la zone morte « tient » la position précédente (head.py:94-96). Une dérive lente plus petite que 0,003 rad par image ne bouge jamais le curseur. À vérifier en usage réel.

**Défile**
- Pas lu en détail. Il utilise `raw_y`, qui n'est pas borné (head.py:108). Les vérifications en usage réel sont déjà demandées dans #32.

**Mode Chrome**
- Approche actuelle : la grammaire Vosk change et des touches sont simulées (c'est accepté pour Chrome).
- Alternative : UI Automation, pour lire l'onglet actif et les liens. C'est utile pour #24 (numéros sur les liens) et #26 (onglet par numéro). Ces deux idées sont déjà dans les issues.

**Rappels / timers / calendrier (reminders.py)**
- Approche actuelle : Haiku répond en JSON. La réponse est extraite avec la regex `\{.*\}` (reminders.py:150-153), puis validée.
- Alternative : demander un JSON strict à `claude -p`, avec `--output-format json` ou un schéma, au lieu d'une regex gourmande. La regex prend tout du premier `{` au dernier `}`, ce qui casse si la réponse contient deux objets.
- Gain : moins d'échecs de type « pas de JSON ».
- Risque : faible, la validation existe déjà.

**Volume (volume.py)**
- Bon choix (API native). On pourrait réutiliser une seule interface COM au lieu de la recréer à chaque commande. Le gain est négligeable.

**Lancement d'applis (apps.py)**
- Approche actuelle : un PowerShell `Get-StartApps`, avec jusqu'à 30 s d'attente (apps.py:49). L'historique vient du registre UserAssist, dont les noms sont chiffrés en ROT13 (format interne, non documenté).
- Alternative : lister le dossier virtuel `shell:AppsFolder` en COM (IShellItem / Shell.Application), dans le processus même.
- Gain : pas de PowerShell à lancer (environ 1 s de démarrage), pas de JSON à analyser.
- Risque : du code COM à écrire. UserAssist peut changer de format avec une mise à jour de Windows.

**VS Code (vscode.py)**
- Approche actuelle : pour passer une fenêtre au premier plan, le code simule un appui sur Alt avec `keybd_event`, puis appelle AttachThreadInput (vscode.py:44-50). Il fait aussi un Alt+Tab simulé (vscode.py:105-109). Il y a des `sleep` fixes de 0,05 à 0,4 s (vscode.py:85, app.py:745).
- Alternatives :
  - Utiliser `SendInput`, qui existe déjà dans output.py, au lieu de `keybd_event` (déprécié).
  - Après le passage au premier plan, attendre que `GetForegroundWindow()==hwnd` soit vrai, avec un délai maximum, au lieu d'un sleep fixe.
  - Supprimer l'Alt+Tab simulé si `SetForegroundWindow` suffit.
- Gain : moins de focus perdu sur une machine lente.
- Risque : faible.

**Discord (discord_link.py + leveldb_mini.py)**
- Approche actuelle : un lecteur LevelDB maison. Il copie tous les fichiers .ldb/.log dans un dossier temporaire à chaque lecture (leveldb_mini.py:113-121). Ce format est interne à Discord et non documenté.
- Alternatives :
  - Copier seulement les fichiers modifiés depuis la dernière lecture (en comparant mtime et taille).
  - À terme, utiliser le RPC Discord. C'est déjà prévu dans #6.
- Gain : moins d'accès disque.
- Risque : le format change, et Iris le découvre en silence. Il faut journaliser « raccourcis introuvables ».

**Sons (sounds.py)**
- Bonne approche : un seul flux sounddevice qui mélange les sons, et qui se tait si la carte son plante. Rien à changer.

**Overlay / UI / boucle principale (app.py, ui.py)**
- Approche actuelle : la boucle interroge en continu, avec `time.sleep(0.002)` quand il n'y a rien de neuf (app.py:502).
- Alternative : attendre directement sur `camera.read(seq, timeout)`, qui bloque déjà sur une `Condition` (camera.py:153). Plus besoin du sleep de 2 ms.
- Gain : moins de réveils du processeur.
- Risque : les autres sources (voix, queue) doivent garder un délai de réponse court. Le timeout de 50 ms convient. ui.py n'a pas été lu.

**Config (config.py)**
- Approche actuelle : `json.dump` écrit directement dans `config.json` (config.py:170-172). Si l'appli plante pendant l'écriture, le fichier est tronqué. Au prochain lancement, tous les réglages reviennent aux valeurs par défaut sans prévenir (config.py:162).
- Alternative : un fichier temporaire puis `os.replace`, comme pour les rappels. Et journaliser quand le fichier est illisible.
- Gain : on ne perd plus les réglages.
- Risque : aucun.

**Stats (stats.py)**
- Approche actuelle : psutil, pynvml, et un fil qui mesure toutes les secondes, seulement quand le panneau est visible. C'est bien. Pas lu en détail.

## Constats prioritaires
| # | Feature / où | Problème (preuve) | Approche proposée | Gravité H/M/B | Effort XS/S/M/L |
|---|---|---|---|---|---|
| 1 | config.py:170-172 | Le fichier est écrit sans protection. Un crash pendant l'écriture efface tous les réglages au lancement suivant, sans prévenir (config.py:162). | Fichier temporaire puis `os.replace`, et journaliser quand le fichier est illisible | H | XS |
| 2 | vscode.py:44-50, 105-109 | Passage au premier plan par `keybd_event` Alt et Alt+Tab simulé, puis attente fixe. Le focus peut être perdu. | `SendInput`, puis attendre `GetForegroundWindow()==hwnd` avec un délai maximum | M | S |
| 3 | reminders.py:150 | La regex `\{.*\}` est gourmande et fragile si la réponse contient du texte ou deux objets. | JSON strict demandé à `claude -p` (`--output-format json` ou un schéma) | M | S |
| 4 | leveldb_mini.py:113-121 | Format Discord non documenté, et tout est recopié à chaque lecture. | Copier seulement les fichiers modifiés et journaliser quand ça échoue. Le RPC est prévu dans #6. | M | S |
| 5 | apps.py:49 | Un PowerShell est lancé à chaque fois, avec 30 s d'attente maximum. UserAssist est un format interne (ROT13). | Lire `shell:AppsFolder` en COM dans le processus | M | M |
| 6 | voice.py:291-299 | La parole est détectée par un seuil d'énergie qui s'adapte. Les bruits forts réveillent le moteur libre. | Un vrai détecteur de voix (Silero ONNX ou webrtcvad) comme brique | B | M |
| 7 | app.py:502 | La boucle tourne à vide avec un sleep de 2 ms. | Bloquer sur la `Condition` de la caméra (camera.py:153) | B | S |
| 8 | head.py:94-96 | La zone morte « tient » la position. Une dérive très lente peut être ignorée (à vérifier). | Zone morte mesurée par rapport à la dernière position envoyée, ou gain selon la vitesse (#17) | B | S |
| 9 | hand.py:79 | La vitesse est lissée par une EMA séparée du One Euro. | Utiliser la dérivée du One Euro (à vérifier) | B | S |

## Décisions à prendre par l'utilisateur
- **Détecteur de voix** : accepter un VAD tiers (Silero / webrtcvad) comme brique, ou en écrire un simple soi-même ?
- **Lancement d'applis** : remplacer `Get-StartApps` par la lecture COM de `shell:AppsFolder` (plus de code, mais plus rapide) ?
- **Réponses de Haiku** : imposer un JSON strict, ce qui change le prompt des rappels ?

## Note globale du périmètre : 7,5/10
Les briques clés sont bien choisies : One Euro, grammaire Vosk, VAD de Whisper, Core Audio, SendInput. Les points faibles sont localisés : la config est enregistrée sans protection, le focus de VS Code est forcé, et deux formats internes ne sont pas documentés (Discord, UserAssist).
