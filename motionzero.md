# motionzero — contrôle de l'ordinateur par gestes de la main (webcam)

Projet perso, créé le 2026-11-08. Objectif : contrôler l'ordinateur avec la main devant la webcam, sans clavier, parce que les mains fonctionnent moins bien.

## 1. Besoins

- Tourner les pages d'un livre (lecture dans un navigateur ou en PDF) d'un mouvement de main.
- Mode souris pour de petits gestes : entrer, sortir, déplacer, clic gauche, clic droit.
- Déclencher la dictée vocale de Claude Code dans VS Code par un geste.
- Tout se fait par des gestes de la main. Le clavier n'est jamais requis pour l'utilisateur. Quand l'appli envoie une touche au système (flèche pour tourner la page), c'est acceptable.

Matériel : Windows 11 Home, un seul écran 1920x1080, webcam UGREEN Camera. Python n'est pas installé (au 2026-11-08).

## 2. Recherche de projets existants (résumé)

Brique commune : MediaPipe Hand Landmarker (21 points par main, CPU, webcam simple).

Projets proches : ColeAugusta/Flip, shaunak99/hand_gesture_recognition, ofnote/gestop, zunza5/handpointer, jorisparet/hapoco, Gest (Bartosz Marcinkowski), vendotha/gestura, arshtiwari2004/handsfree-os, gijs/webcamswiper, Webcam Swiper (Google, 2012).

Conclusions de l'audit (2026-11-08) :
- HandPointer : aucune licence trouvée, code non réutilisable.
- HapOCo : GPL-3.0, contaminerait le code. Idée intéressante : contrôle relatif de type trackpoint.
- gestop : Apache-2.0, bonne architecture (tracker, recognizer, executor) mais pour Linux.
- Flip, Gest, shaunak99 : non vérifiés.
- Décision : écrire de zéro en reprenant seulement les idées.

## 3. Décisions validées

| Sujet | Choix |
|---|---|
| Langage | Python 3.12 (64 bits) en environnement virtuel |
| Détection | MediaPipe HandLandmarker, version épinglée, une seule main (la droite) |
| Capture | OpenCV, 640x480, 30 fps, thread dédié qui garde la dernière image |
| Envoi des entrées | SendInput via ctypes, coordonnées absolues, DPI déclaré au démarrage. Pas de pyautogui. |
| Code | Écrit de zéro |
| UI | PySide6, fenêtre qui ne prend pas le focus, mini-barre toujours visible |
| Arrêt d'urgence | Gros bouton STOP seulement, toujours visible. Pas de geste d'arrêt. |
| Dictée | /voice de Claude Code, pouce levé tenu = on parle tant qu'il est levé |
| Clic | Pincement pouce-index ET clic par survol prolongé (dwell), activé par défaut |
| Lancement | Raccourci bureau (double-clic) |
| keybindings.json | Autorisé : l'assistant le modifie après lecture, avec sauvegarde |
| Pages | Flèche droite et flèche gauche envoyées par l'appli (configurable) |
| Retour d'état | Bips + retour visuel |
| Mains | Main droite, pincement pouce-index possible, trois doigts repliables |

## 4. Gestes (zéro clavier)

| Geste | Durée | Effet | Modes |
|---|---|---|---|
| Paume ouverte | 0,8 s | Armer, passer en lecture | Repos |
| Balayage main ouverte | mouvement | Page suivante (droite vers gauche) ou précédente | Lecture |
| Index pointé, autres doigts repliés | 0,6 s | Entrer en mode souris | Repos, Lecture |
| Poing fermé | 1 s | Sortir du mode souris | Souris |
| Main absente | 2 s | Retour au repos, relâche tout | Lecture, Souris |
| Pincement pouce-index | bref | Clic gauche | Souris |
| Pincement pouce-majeur | bref | Clic droit (à valider sur l'utilisateur) | Souris |
| Maintien du curseur sur un bouton | environ 1 s | Clic (anneau de progression) | Souris |
| Pouce levé | 0,4 s | Dictée tant que tenu | Repos, Lecture |

Plus tard : double-clic, glisser-déposer, scroll.

Curseur : piloté par le centre de la paume, lissage One Euro, zone morte, curseur figé juste avant un pincement pour éviter la dérive.

États : DÉSACTIVÉ, REPOS, LECTURE, SOURIS, plus un drapeau DICTÉE superposé. Délai de 800 ms entre deux transitions.

## 5. Sécurité

- Chien de garde : tout clic ou touche maintenue est relâché si la main disparaît 0,5 s, si l'appli plante ou si STOP est cliqué. Plafonds : clic 5 s, glisser 10 s, dictée 60 s. Tout est relâché au démarrage.
- Pause automatique : main absente 2 s = retour au repos, réarmement obligatoire.
- Aucun clic hors du mode souris.
- Dictée désactivée en mode souris (le pouce du poing peut se lever).
- Ctrl+Alt+F12 reste disponible en bonus pour un aidant, sans dépendance.
- Pas de démarrage automatique avec Windows.
- Traitement 100 % local, aucune image enregistrée par défaut.

Conflits à tester : paume (armement) vs balayage ; poing vs pouce levé ; clic gauche vs clic droit (doigt le plus proche du pouce, marge nette).

## 6. Dictée dans VS Code

Ce n'est pas Ctrl+D (conflit avec « sélectionner la prochaine occurrence » dans VS Code). La dictée intégrée /voice se déclenche avec la barre Espace, maintenue ou en bascule. Elle est exclue en session distante (SSH, Dev Container, Codespaces). Le raccourci se change en associant voice:pushToTalk dans ~/.claude/keybindings.json. Étape 5 : lire le fichier, le sauvegarder, le modifier, tester.

## 7. Architecture proposée

```
motionzero/
  requirements.txt
  config.default.json
  models/hand_landmarker.task
  src/motionzero/
    app.py            # point d'entrée
    engine.py         # façade moteur pour l'UI (start/stop/pause, événements)
    config.py
    capture/camera.py
    vision/landmarker.py
    gestures/         # features, swipe, pinch, poses
    control/          # state_machine, mouse, keys, input_backend (SendInput), safety
    util/             # one_euro, geometry
  ui/                 # PySide6, ne dépend que de engine.py
  tools/record.py, replay.py   # positions de main (sans images)
  tests/
```

UI : le moteur tourne dans un thread, l'UI envoie des commandes (start, stop, set_mode, trigger, apply_settings) et reçoit des signaux (frame_ready, hand_detected, mode_changed, gesture_detected, error).

## 8. UI

- Fenêtre principale environ 1000x680 : bandeau de mode (Repos gris, Lecture bleu, Souris orange, avec texte et icône), aperçu caméra avec la main dessinée, gros boutons Démarrer/Arrêter/STOP (au moins 64 à 80 px), bascule de mode, boutons de test de chaque action, boutons -/+ pour les réglages, journal de 5 lignes, case Sons, thème clair/sombre.
- Mini-barre toujours au premier plan (environ 420x64 px), sans prise de focus.
- Police Segoe UI. Bips différents selon l'événement.

## 9. Étapes

0. Test de faisabilité : installer Python 3.12, MediaPipe (version épinglée), OpenCV, PySide6 ; télécharger hand_landmarker.task ; webcam + curseur par la paume via SendInput. Mesurer sur 2 minutes. Critères proposés (non sourcés) : détection sous 40 ms dans 95 % des cas, au moins 25 images/s, CPU sous 40 %, 95 % des 50 pincements détectés, moins d'un clic involontaire par 5 minutes. Si le pincement échoue : contact index-majeur avant de changer de modèle. Lire les notes de version de MediaPipe 1.x.
1. Enregistrer et rejouer des positions de main.
2. Mode lecture : armement et balayage.
3. Mode souris : entrée, sortie, curseur, dwell.
4. Clics : gauche puis droit.
5. Dictée et keybindings.json.
6. UI PySide6 (moteur factice d'abord).
7. Essai réel en lisant, réglages.

## 10. Risques et points non vérifiés

Risques : fiabilité du pincement sur webcam 2D, tremblements et faux déclenchements, latence et CPU sur la machine, fenêtres administrateur qui ignorent les entrées injectées (UIPI).

Non vérifié : performances de MediaPipe sur PC ; notes de version MediaPipe 1.x (l'API a pu changer) ; compatibilité exacte Python 3.13 ; URL officielle du modèle (la forme storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task vient d'une source non officielle) ; Voice Access de Windows comme filet de secours ; activité récente des projets GitHub.

Découverte MediaPipe (2026-11-08) : v1.2.2 du 3 novembre 2026 sur PyPI, roue py3-none-win_amd64, classifiers Python 3.9 à 3.14, licence Apache-2.0.

## 10 bis. Résultats de l'étape 0 (2026-11-08)

Installé : Python 3.12.10 (winget, utilisateur), venv `.venv`, mediapipe 1.2.2, opencv-python 5.0.0.93, numpy 2.5.4. Modèle `models/hand_landmarker.task` (7,8 Mo) téléchargé depuis l'URL storage.googleapis.com (fonctionne).

Mesure webcam + détection (`tools/bench_camera.py`, 20 s, mode VIDEO, une main) :
- webcam UGREEN, indice 0, 640x480 ;
- détection : 6,2 ms en moyenne, 6,7 ms au 95e centile (critère < 40 ms : OK) ;
- main détectée sur 100 % des images ;
- CPU : 17 % d'un cœur, 1,4 % du total (12 cœurs) (critère < 40 % : OK) ;
- 20 images/s (critère >= 25 : NON atteint). La limite vient de la webcam (la détection ne prend que 6 ms), probablement l'exposition automatique en lumière faible. Pistes : plus de lumière, réglage d'exposition, CAP_MSMF au lieu de CAP_DSHOW, MJPG.

Test curseur SendInput (`tools/test_sendinput.py`) : 4 coins + centre atteints avec 0 pixel d'écart, appel < 0,25 ms, DPI per-monitor V2 OK.

Test du pincement avec l'utilisateur : abandonné (douleur à la main). Le pincement sera réglé à partir d'un enregistrement, plus tard.

Incidents :
- Image grise dans la fenêtre du test de pincement : la caméra captait bien (statistiques normales), le bug venait de la fenêtre (WINDOW_NORMAL + redimensionnement + premier plan). Corrigé avec WINDOW_AUTOSIZE (vérifié : image nette, ~23 img/s).
- Ralentissements du PC de ~2 s : survenus pendant les diagnostics qui ouvraient la caméra 5 fois de suite (dont 2 fois en MSMF). Cause non confirmée. L'appli ouvre la caméra une seule fois, en DSHOW.

## 10 ter. Étapes 1 à 3 : code écrit (2026-11-08)

- `src/motionzero/` : config, filters (One Euro), hand (poses), gestures (pose tenue, balayage, pincement, survol), core (machine à états), output (SendInput + chien de garde), camera, sounds, app, replay.
- Lancer : `.venv\Scripts\python.exe -m motionzero` (ou `--simulation` pour ne rien envoyer). Arrêt : fermer la fenêtre d'aperçu.
- Étape 1 : `tools/record.py` (points de la main seulement) et `tools/replay.py`.
- 19 tests automatiques sur mains simulées (`pytest`), tous verts. Bug trouvé et corrigé par les tests : le clic droit ne se relâchait pas en revenant en index pointé.
- Délai de retour au repos en lecture : 60 s (validé). Gauche ou droite indifféremment.
- Pincement réglé sur un enregistrement réel : clic jusqu'à 2 s de pincement, relâchement au-delà de 0,45.

## 10 quater. Images corrompues et ralentissements (2026-11-08)

Symptôme (2 fois, captures longues) : 70 % du haut en neige grise, bas figé alternant bleu/vert et miroir, PC qui ralentit, ~1 img/s.
Diagnostic (3 agents, sans ouvrir la caméra) :
- webcam Sonix 0C45:2283, pilote générique usbvideo, USB 2.0 ; elle était sur le contrôleur du chipset AMD (43FC). Rebranchée sur un port relié au CPU (contrôleur 15B7) ;
- aucune erreur USB dans les journaux ; format non compressé YUY2 qui sature l'USB 2.0 (hypothèse principale) ;
- bugs de mes scripts : fenêtre non rafraîchie quand la caméra cale (fenêtre fantôme), boucle à 100 % d'un cœur, suivi de 2 mains coûteux.
Corrections : MJPG demandé avant la taille, copie des images, rejet des images corrompues (`frame_is_valid`), reconnexion automatique après 2 s, verrou d'instance unique, arrêt propre, détection plafonnée à 20 img/s, 1 main suivie, bandeau « caméra perdue », fenêtre toujours rafraîchie. Scripts de diagnostic risqués supprimés. 27 tests verts.
Essais en simulation : 20 s puis 2 min, 0 image rejetée, 0 reconnexion, CPU total ~7 % (max 11 %), 19 img/s. La caméra reste en YUY2 (MJPG refusé) ; c'est le changement de port qui a réglé la neige.

## 11 bis. Gestes v2 (2026-11-08) — remplace les gestes de la section 4

Retour de l'utilisateur : pincements et poses tenues épuisants et douloureux ; pouce-index et pouce-majeur indistinguables ; trop de clics involontaires (19 en ~1 min 40) ; les deux mains doivent être utilisables.
Concept retenu (agent de conception + agent de vérification des sources, 18 recherches) : aucune forme de doigts, aucun pincement. Seuls comptent la présence de la main, le centre de la paume, le mouvement et l'immobilité.

- LECTURE (mode par défaut) : paume dans la bande droite de l'image (x > 0,80) pendant 0,35 s = page suivante ; bande gauche (x < 0,20) = précédente ; revenir au centre (0,30-0,70) pour réarmer ; 1 s minimum entre deux pages.
- Entrer en SOURIS : main immobile 1,5 s au centre -> bulle « SOURIS ? » ; monter un peu la main (> 0,05) = oui ; ne rien faire 2 s = non (pas de nouvelle bulle sans avoir bougé).
- SOURIS : curseur relatif type pavé tactile (gain 1,5 à 5 selon la vitesse) ; retirer la main = la reposer ailleurs. Main immobile 0,8 s -> menu à 4 directions : gauche = clic gauche, droite = clic droit, haut = double clic, bas = retour lecture ; rien pendant 1,5 s = annulé. Il faut déplacer le curseur d'au moins 80 px avant un nouveau menu, et 0,5 s de récupération après un clic. Main absente 2 s = retour lecture.
- Deux mains suivies en même temps (`HandTracker`) : celle qui bouge agit, l'autre peut rester posée ; une main perdue 1 à 3 images est conservée.
- Tous les seuils sont dans `config.py` (réglables). Le seuil d'immobilité (0,012) est à calibrer sur la main posée de l'utilisateur.
- Sources retenues : Kurtenbach & Buxton 1993 (4 directions), Gaze Interaction Library de Microsoft (~0,75 s), Camera Mouse (1 s, temps de récupération), Accot & Zhai 2002, Vogel & Balakrishnan 2005, Casiez 2012 (One Euro).
- 27 tests verts. Essayé en simulation : pages OK (14 pages en ~40 s).
- Défilement (lecture) : paume en haut / en bas de l'image (bandes y < 0,25 / y > 0,75), après 0,3 s un cran toutes les 0,15 s.

## 11 ter. Commandes vocales (2026-11-08)

- Moteur : Vosk 0.3.45, modèle `vosk-model-small-fr-0.22` (41 Mo, hors ligne), grammaire fermée. Micro via sounddevice (mode partagé : la dictée Claude peut l'utiliser aussi).
- Écoute : mot de réveil « iris » (dit seul) OU bulle / menu affichés (main immobile) -> écoute 4 s, prolongée à chaque commande. « stop » est toujours écouté.
- Règle anti-faux-positifs : un mot n'est accepté que s'il est dit SEUL (aucun mot inconnu, un seul mot).
- Vocabulaire : iris, clic, double, menu (clic droit), glisse / lâche, page, retour, défile, entrée, annule (Échap ; « échap » n'existe pas dans le modèle), copie, colle, dictée (pas encore branchée), pause (désactive, « iris » reprend), stop.
- Mot + geste : « défile » puis la hauteur de la main règle le sens et la vitesse ; « clic » pendant que le menu est ouvert.
- Auto-test sans micro (`tools/voice_selftest.py`, voix de synthèse Hortense) : 16/16 mots reconnus, ~37 ms ; 0 faux positif sur 12 phrases ordinaires après filtrage (2 sans le filtre). Une seule voix testée : à vérifier avec la vraie voix de l'utilisateur.
- Activation : option `--voice` (le micro n'est jamais ouvert sans elle). 45 tests verts.

## 11. Sources

- https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python
- https://developers.google.com/edge/mediapipe/solutions/customization/gesture_recognizer
- https://pypi.org/project/mediapipe/
- https://github.com/google-ai-edge/mediapipe
- https://github.com/ColeAugusta/Flip
- https://github.com/shaunak99/hand_gesture_recognition
- https://github.com/ofnote/gestop
- https://github.com/zunza5/handpointer
- https://github.com/jorisparet/hapoco
- https://code.claude.com/docs/en/voice-dictation
- https://marketplace.visualstudio.com/items?itemName=jsaluja.claude-voice
- https://pypi.org/pypi/PySide6
- https://cristal.univ-lille.fr/~casiez/1euro
