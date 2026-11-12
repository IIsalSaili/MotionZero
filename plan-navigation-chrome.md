# Plan : mode navigation Chrome

Statut : décisions validées le 2026-11-12.

## Principe
- Nouveau mode `CHROME` à côté de NEUTRE / LECTURE / SOURIS.
- Entrée : « iris chrome ». Ça ouvre ou amène Chrome devant, comme aujourd'hui, puis active le mode.
- Sortie automatique dès que Chrome n'est plus au premier plan. On sort aussi par un autre mode ou par « stop ».
- **Voix uniquement.** Lever la main longtemps est douloureux : aucun geste propre à ce mode. Une pédale USB pourra venir plus tard (issue).
- **« iris » reste obligatoire** avant chaque commande, pour ne rien déclencher en parlant avec quelqu'un.
- Avant chaque raccourci, on vérifie que Chrome est au premier plan, sinon rien n'est envoyé. Les touches simulées sont acceptées pour Chrome (l'interdit vaut pour Claude Code).

## Commandes (toutes précédées de « iris », mode Chrome seulement)
| Mot | Action |
|---|---|
| retour / avance | page précédente / suivante (Alt+← / Alt+→) |
| suivant / précédent | onglet suivant / précédent |
| onglet / ferme / rouvre | nouvel onglet / fermer l'onglet / rouvrir le dernier fermé |
| recherche | barre d'adresse, puis dictée (comme « type ») |
| recharge, favori | F5, Ctrl+D |
| haut / bas, monte / descends | début / fin de page, page par page |
| agrandis / réduis | zoom |
| skip / back | déjà existants (±10 s sur YouTube) |

Hors du mode Chrome, ces mots ne font rien, sauf « ferme » qui garde son sens habituel. Les autres commandes d'Iris restent utilisables. Reporté : #24 (numéros sur les liens), #25 (pédale), #26 (onglet par numéro, favoris par nom).

## Cliquer un lien : hints numérotés (étape 2)
- Extension Chrome (MV3) chargée en mode développeur. Un content script numérote les liens visibles et clique avec `element.click()`.
- Liaison par WebSocket sur `127.0.0.1` avec un jeton partagé. Les messages passent par une queue lue dans la boucle moteur.
- Les numéros disparaissent après 8 s ou sur « annule ». Un nombre n'est accepté que si des numéros sont affichés.
- Écartés : le port de débogage Chrome (bloqué sur le profil normal depuis Chrome 136, et il expose les cookies) et l'UI Automation (lente et incomplète).

## Visuels
- Le logo reste toujours le logo classique noir. Les variantes par mode et la main verte disparaissent.
- Seul le cercle autour de la main change de couleur : neutre par défaut, orange en mode souris, bleu en mode Chrome.
- Quand une action est validée, le cercle clignote en vert.

## Étapes
1. Mode `CHROME`, commandes par raccourcis, sortie automatique, couleurs du cercle. Tests : Chrome pas devant, commande sans « iris », mot inconnu, sortie automatique.
2. Extension et numéros sur les liens.
3. Issues : pédale USB, ouvrir un favori par son nom.
