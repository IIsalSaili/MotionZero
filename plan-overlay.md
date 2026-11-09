# Plan : l'interface de motionzero devient un overlay

## Objectif
L'interface ne vit plus dans une fenêtre à part. Elle se dessine **par-dessus tout l'écran**, laisse passer les clics vers les applis en dessous, et reste lisible sur n'importe quel fond. Le seul élément cliquable est le bouton STOP.

Étude et maquettes : https://claude.ai/artifact/CGCu4rG1t7qEx5NR4MSgRB

## Choix validés (9 novembre 2026)
| Sujet | Choix |
|---|---|
| Style | **Dot Iris** : une seule « île » noire en haut au centre. Police **Atkinson Hyperlegible**. Rouge réservé au STOP. |
| Mode souris | L'anneau de survol et l'action prévue suivent le curseur. Loupe ×2 avec grille 3×3 appelée par « Iris, zoom ». |
| Dictée | L'île du haut s'étire : niveau du micro, texte reconnu, réponse. |
| Lecture | Dock en bas avec une ligne pointillée à dépasser pour tourner la page. |
| Survol prolongé | Fait **toujours un clic gauche**. |
| Clic droit | Deux modes, voir plus bas. |
| Arrêt d'urgence | **Bouton STOP** dans un petit overlay en bas à droite, cliquable au survol ou à la souris. Pas de touche dédiée (Ctrl+Alt+F12 reste en bonus pour un aidant). |
| Menu Démarrer | Il passe au-dessus de l'overlay. Accepté, pas de version signée. |

## Les deux modes de clic
On change de mode par la voix : « Iris, mode mains » / « Iris, mode voix ». Le mode s'affiche dans l'île.

**Mode mains (par défaut)**
- La main qui pointe déplace le curseur. Pincement de cette main = clic gauche.
- Pincement de **l'autre main** = clic droit, à l'endroit du curseur.
- Les rôles suivent la main qui pointe, pas la gauche ou la droite fixe. Les deux mains restent donc équivalentes, comme aujourd'hui.

**Mode voix**
- La main ne fait que pointer. Aucun pincement n'est pris en compte.
- « clic », « clic droit », « double clic » cliquent à l'endroit du curseur.
- Le curseur est figé 150 ms avant le mot, pour ne pas cliquer à côté.

Dans les deux modes, le survol prolongé reste un clic gauche.

Retours visuels (repris de Meta Quest, Ultraleap et Apple) :
- l'anneau se resserre à mesure que le pincement se ferme, avant le clic ;
- anneau d'une autre forme et d'une autre teinte pour le clic droit ;
- flash et petit son à chaque clic ;
- pause visible après chaque clic, pour éviter les clics en rafale ;
- « Iris, recentre » remet le curseur au milieu de l'écran.

Ce que dit la recherche : pointer puis dire « clic » est précis et peu fatigant ; le pincement est plus rapide. Les modes doivent être des bascules, jamais un geste à tenir. Aucun projet open source trouvé ne fait « une main pointe, l'autre clique » : c'est une idée propre à motionzero.

## Ce qu'on garde, ce qu'on change
- **Gardé :** la caméra, MediaPipe, `core.py` (modes, gestes, sécurité), `output.py` (SendInput), la voix.
- **Changé :** l'affichage. Aujourd'hui, `overlay.py` dessine avec OpenCV sur l'image de la webcam, dans une fenêtre normale. Il sera réécrit avec Qt (PySide6) et QPainter.
- La vue caméra devient une petite vignette, masquable.

## Architecture
```
Thread caméra (MediaPipe + Core)  ──état──▶  Contrôleur d'overlay (thread Qt)
  avant chaque clic : le point est-il       ├─ Verre plein écran (transparent aux clics, exclu des captures)
  sur le STOP ? oui → action interne        ├─ Fenêtre STOP séparée (cliquable, ne prend jamais le focus)
                                            ├─ Vignette caméra (optionnelle)
                                            └─ Registre des zones de l'overlay (pixels physiques)
```

## Étapes
Chaque étape se termine par un essai réel avant de passer à la suivante.

0. **Corriger la mesure du pincement.** Dans `hand.py`, les distances sont calculées sur des coordonnées qui n'ont pas la même échelle en largeur et en hauteur (image 640×480). Le même pincement donne une valeur différente selon que la main est droite ou de côté. Multiplier x par 4/3 avant tout calcul, puis recaler les seuils sur un enregistrement.
   *Essai :* les tests rejoués (`tests/`) passent, puis 20 pincements main droite et main de côté.
1. **Boucle Qt.** Passer de la boucle `cv2.waitKey` à `QApplication`. La caméra, MediaPipe et `Core` tournent dans un worker déplacé dans un QThread, qui envoie seulement l'état (pas les images en pleine résolution). La fenêtre OpenCV est remplacée par une vignette Qt : `opencv-python` et PySide6 entrent en conflit, on passe à `opencv-python-headless`.
   *Essai :* même comportement qu'avant, sans ralentissement.
2. **Verre transparent.** Fenêtre plein écran, sans bordure, toujours au-dessus, transparente aux clics, invisible dans les captures d'écran. On y dessine seulement le curseur et l'anneau. Les options Qt sont posées une seule fois à la création (les changer ensuite fait clignoter la fenêtre). On ne repeint que la zone autour du curseur : Qt recopie toute la fenêtre à chaque image pour ce type de fenêtre, donc on mesure le CPU, et on passe à Qt Quick s'il est trop haut.
   *Essai :* en mode souris, cliquer dans Chrome et VS Code à travers l'overlay.
3. **Bouton STOP.** Petit overlay séparé en bas à droite, cliquable au survol ou à la souris. Les options Qt ne suffisent pas à l'empêcher de prendre le focus : on ajoute le style Windows « sans activation » directement. Le STOP lève un drapeau lu par le thread caméra, il n'attend jamais celui-ci.
   *Essai :* STOP au survol et à la souris, pendant un clic maintenu.
4. **L'île.** Mode, état de la main, toasts de confirmation, message « main perdue ». Fond noir opaque, police Atkinson.
   *Essai :* lisible sur fond blanc, fond noir, photo chargée.
5. **Modes de clic.** Mode mains (clic droit par l'autre main) et mode voix (« clic », « clic droit », « double clic », « mode voix », « mode mains »). Ajout des mots à la grammaire Vosk.
   *Essai :* 20 clics droits dans chaque mode, compter les erreurs.
6. **Lecture.** Dock à seuil.
   *Essai :* 50 pages d'un livre, compter les pages tournées par erreur.
7. **Dictée et réponse de Claude** dans l'île, à la place du panneau actuel.
8. **Loupe et grille** (« Iris, zoom », « Iris, grille »). Grille 3×3 qui se raffine, chiffres enchaînables (« grille 5 2 »), fermée par le clic, comme Talon et Voice Access. Une étude a trouvé que la loupe n'aidait pas quand on clique à la voix : on la teste avec toi avant de la garder.
9. **Réglages et finitions :** estompage après 3 s d'inactivité, respect de « Effets d'animation » de Windows, vignette caméra masquable.

## Valeurs de départ
« Sans source » = valeur de départ raisonnable, mais aucune étude trouvée. À régler sur toi.

| Réglage | Valeur | Plage | Source |
|---|---|---|---|
| Survol avant clic | 1000 ms | 600 à 2500 ms | Manuel Camera Mouse 2018 ; études SLA (800 ms à 2,5 s) |
| Tolérance de tremblement pendant le survol | 30 px | 20 à 60 px | Camera Mouse (Betke, Gips, Fleming 2002) |
| Anneau visible après | 200 ms d'arrêt | 150 à 250 ms | Microsoft, regard et dwell |
| Pause après un clic | 1000 ms | 500 à 2000 ms | Option de Camera Mouse ; valeur sans source |
| Position du clic au pincement | 150 ms avant le pincement | | sans source |
| Lissage One Euro | mincutoff 1,0 Hz, beta 0,007 | mincutoff 0,3 à 1,5 | Casiez ; à baisser si tremblement |
| Main perdue : tout relâcher | moins de 100 ms | | Meta (pincement relâché à la perte de suivi) |
| Réarmement après retour de la main | 250 ms de suivi stable | | sans source |
| Taille des cibles de l'overlay | 18 mm, environ 70 px | 12 à 25 mm | CHI 2017 (tactile, troubles moteurs) |
| Estompage de l'île au repos | 25 % après 3 s | | sans source |

Pas de données publiées sur les seuils de pincement MediaPipe ni sur les faux clics : ils se règlent sur toi, avec une jauge en direct (idée de Project Gameface).

## Limites connues
- Le menu Démarrer, la barre des tâches et l'écran UAC passent au-dessus de l'overlay.
- Les applis lancées en administrateur refusent les clics simulés.
- Les jeux en plein écran exclusif cachent l'overlay. En fenêtré sans bordure, ça marche.

## Dépendances
- Ajouter `PySide6` (version épinglée).
- Remplacer `opencv-python` par `opencv-python-headless`, même version.

## Sources principales
- Qt, source du plugin Windows (transparence aux clics) : https://raw.githubusercontent.com/qt/qtbase/dev/src/plugins/platforms/windows/qwindowswindow.cpp
- SetWindowDisplayAffinity : https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity
- Fenêtre sans focus avec Qt : https://forum.qt.io/topic/140542/how-to-create-a-window-without-focus-all-the-time
- Apple Dwell : https://support.apple.com/en-au/guide/mac-help/mchl437b47b0/mac
- Ultraleap TouchFree : https://docs.ultraleap.com/TouchFree/touchless-interfaces/ui-components.html
- Meta, interfaces pour les mains : https://developers.meta.com/vr/design/hands-ui-best-practices/
- Regard, pincement, survol et voix comparés : https://arxiv.org/html/2602.12406
- Camera Mouse : http://www.cameramouse.org/downloads/CameraMouse2018Manual.pdf
- Microsoft, regard et dwell : https://learn.microsoft.com/en-us/windows/mixed-reality/design/gaze-and-dwell-eyes
- Cibles pour troubles moteurs (CHI 2017) : http://library.usc.edu.ph/ACM/CHI%202017/1proc/p6056.pdf
- Filtre One Euro : https://github.com/casiez/OneEuroFilterArduino
- Normalisation du pincement MediaPipe : https://github.com/edw1nzhao/p5-garden/pull/16
