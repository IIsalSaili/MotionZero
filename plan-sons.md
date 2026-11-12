# Plan : nouvelle identité sonore

Statut : livré le 2026-11-12 avec des sons réels (packs libres, voir assets/sounds/CREDITS.md) au lieu de sons fabriqués : « iris » A9, compris B8, pas compris C6, modes et fin de dictée D6, micro prêt et rappel D5, plus de son de clic, alarme I7 (berceuse) qui monte en 60 s.

## Constat
- 11 sons : des notes synthétiques tenues à volume fixe (d'où l'effet « cornemuse »), générées par `sounds.py`.
- winsound ne joue qu'un son à la fois (un clic coupe l'alarme), sans réglage de volume.
- Alarme : 0,5 s toutes les 1,5 s, sans fin, toujours au même volume.
- Aucun son pour : commande refusée, erreur, démarrage d'un timer.

## Ambiance visée
« Cloche de verre » douce : une attaque douce, puis le son s'éteint tout seul (jamais tenu), une légère réverbération et une sous-octave pour la chaleur. Tous les sons sont dans la même gamme (ré mineur pentatonique, médium, rien au-dessus de 2 kHz). Quand ça monte, c'est un oui ou un début ; quand ça descend, un non ou une fin. Les sons fréquents sont nettement plus bas que les sons rares, avec une petite variation à chaque lecture pour ne pas lasser.

| Événement | Son |
|---|---|
| « iris » entendu | 2 notes montantes, l'œil s'ouvre (~300 ms) |
| commande comprise | 1 note ronde (~120 ms) |
| refusée / pas compris (nouveau) | 2 notes descendantes, plus graves et douces |
| changement de mode | 3 notes qui partent du même ré ; seule la dernière change selon le mode |
| pause | glissement descendant étouffé |
| clic | « tick » très court et très bas |
| micro prêt / fin de dictée | quinte qui s'ouvre / qui se referme |
| rappel | 3 cloches, réverbération plus longue (~1 s) |
| alarme | le motif du rappel, lent, en boucle, avec des silences |

## Alarme progressive
- Elle part presque inaudible (−40 dB) et monte de façon régulière (linéaire en dB) pendant 60 s, jusqu'à un plafond (−6 dB).
- Le son s'éclaircit en montant, au lieu de seulement devenir plus fort.
- Rien d'aigu ni de dissonant, rythme lent.
- Elle se coupe tout de suite sur « stop », avec un fondu de 30 ms.

## Source des sons : deux candidats, à comparer à l'oreille
1. **Sons fabriqués par Iris** (synthèse numpy) : famille parfaitement cohérente, aucune question de licence, réglables par code. Le risque : que ça sonne « fabriqué ».
2. **Kenney Interface Sounds + Sci-Fi Sounds** (CC0 vérifié, aucun crédit à donner, utilisables dans un dépôt public) : sons réels et propres, mais de familles moins homogènes.

Écartés :
- Pixabay et Mixkit : on n'a pas le droit d'y redistribuer les fichiers bruts, ce qui exclut un dépôt public.
- Zapsplat : crédit obligatoire et redistribution interdite.
- Sons Linux : licences floues.

À vérifier : sons de Material Design (CC-BY ?, l'alarme `alarm_gentle` serait intéressante) et Freesound filtré CC0 (bol chantant ou cloche pour l'alarme).

## Technique
- Remplacer winsound par `sounddevice` + numpy (déjà installés) : un flux de sortie qui mélange les sons. Ça permet la superposition, le volume par son et la montée progressive de l'alarme.
- Le flux tourne dans son propre fil et ne touche jamais `Core`.
- Si la carte son plante ou disparaît, on passe en silence, sans plantage.
- Retirer le `sleep(0.4)` qui bloque la boucle avant le son « micro prêt ».

## Étapes
1. Prototype : générer les sons fabriqués et télécharger les candidats Kenney, puis une démo jouée l'une après l'autre pour comparer à l'oreille.
2. Nouveau lecteur `sounddevice`, nouveaux sons, alarme progressive, sons manquants (refus, erreur, timer). Tests : carte son absente, « stop » pendant l'alarme, deux sons superposés.
