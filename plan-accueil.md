# Plan : refonte de la page d'accueil

Maquettes : artefact « Iris accueil : maquettes » (A onglets, B menu latéral, C tableau unique ; 2 versions chacun).
Le choix de mise en page change seulement l'étape 3 ; le reste vaut pour les trois.

## Constat (22/11)
- Les boutons ont été ajoutés un par un dans une colonne de 400 px : texte qui déborde (« Mode conversation »), styles mélangés, aucun groupe.
- Le panneau Consommation du 11/11 (courbes, cœurs, fils, RAM, carte graphique, modèles) a été réduit à une ligne le 14/11. `stats.py` mesure toujours tout, historique compris : seul le dessin manque.
- Chaque nouveau réglage demande aujourd'hui de toucher 6 endroits (ui, signal, queue, boucle, fichier, pont).

## Étape 1 : un registre des réglages (`reglages.py`, sans Qt, testable)
Un réglage = une entrée, rien d'autre à écrire ailleurs :
```python
Reglage(id="conversation", groupe="Voix", titre="Mode conversation",
        aide="Un mot noyé dans une phrase est ignoré", genre="interrupteur",   # interrupteur | choix | action
        valeurs=("oui", "non"), defaut="oui", fichier="conversation.txt", danger=False)
```
- Groupes fixes, dans l'ordre : Entrées (souris, caméra), Voix (conversation, voix basse, lecture à voix haute des réponses — #9, désactivée par défaut), Sons (volume, réparer le son), Iris (fermer).
- Une seule file `reglages_requests` (id cliqué) lue dans la boucle principale ; un seul signal `reglage(id, valeur)` vers l'interface.
- Chaque réglage déclare sa fonction d'effet (`appliquer(d, valeur)`), appelée dans la boucle principale : jamais Core depuis le fil Qt.
- Lecture et écriture du choix gardé : une fonction commune (remplace read_quiet, read_conversation, read_pointer…).
- Ajouter un réglage plus tard = une entrée + sa fonction d'effet + un test. L'interface le place seule dans son groupe.

## Étape 2 : composants d'interface communs (ui.py)
- `ReglageRow` : titre, aide sur une ligne (coupée proprement, jamais de débordement), contrôle à droite.
- Trois contrôles : interrupteur (96 × 52), choix segmentés (hauteur 52), bouton d'action ; « danger » = rouge.
- Toutes les cibles ≥ 52 px, sans focus clavier (règle actuelle : une touche Espace ne doit rien cliquer).
- Un test vérifie que chaque texte tient dans sa largeur avec la police Atkinson Hyperlegible (QFontMetrics), pour ne plus jamais livrer un bouton qui déborde.

## Étape 3 : la page (selon la maquette choisie)
- Sections : Maintenant (état, mode, image caméra, « ici maintenant », dernières commandes, capteurs), Réglages (tiré du registre), Consommation.
- A / B : une section affichée à la fois (QStackedWidget) ; ajouter une section = une entrée de plus dans la liste de navigation.
- C : tout visible ; les réglages en grille, prévue pour 8 cases puis une ligne de plus.
- Section choisie gardée d'un démarrage à l'autre.

## Étape 4 : retour de la consommation
- Courbe processeur Iris / PC sur 2 min (historique déjà dans `stats.py`), barres RAM et carte graphique (Iris sur PC), fils les plus occupés, état des modèles (Whisper chargé, Vosk, images/s des gestes).
- Dessin QPainter dans un widget à part, mesuré seulement quand la section est visible (règle actuelle de `run_sampler`).

## Étape 5 : tests et doc
- Tests : registre (chaque réglage a titre, aide, groupe connu, effet), bascule et enregistrement de chaque réglage, fichier illisible, voix coupée, textes qui tiennent, section gardée.
- Rendu de la page dans les tests (hors écran) pour les 3 états : normal, caméra coupée, mesures absentes.
- `docs/guide/02-utilisation.md` : une section « Page d'accueil » qui décrit les groupes.

## Hors périmètre
- Aucun nouveau mot vocal. Aucun nouveau réglage ajouté maintenant : seulement la place prévue pour eux.
