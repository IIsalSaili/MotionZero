# Plan : vocabulaire et enchaînements vocaux

Étude du 14/11/2026 : code (voice.py, core.py, app.py, typer.py), journaux du 08 au 14/11 (68 759 lignes). Chaque mot proposé a été vérifié : il est bien dans le modèle de reconnaissance.

Règle de ce plan : **un mot qui marche n'est jamais retiré**. On ajoute le synonyme et l'ancien mot reste valable. Un retrait ne se fait qu'avec ton accord, mot par mot (lot 4).

## Lot 1 : les enchaînements (le plus gênant)

1. **Après une dictée, « envoie » et « annule » marchent seuls pendant 4 s, à compter du moment où le texte apparaît.** Aujourd'hui, les 3 s partent dès la coupure du micro, alors que Whisper écrit le texte jusqu'à 3 s plus tard. Les journaux montrent 9 « envoie » seuls ignorés juste après un « iris type ».
   - La règle vaut pour « type », « recherche », « claude » et « rappel ».
   - Un compte à rebours est affiché.
   - Si tu ne dis rien, la demande disparaît, et « iris envoie » reste possible ensuite.
2. **Pendant cette fenêtre, « envoie » et « annule » sont reconnus plus facilement.** La certitude demandée passe de 0,8 à 0,6, et la deuxième vérification n'exige plus qu'un autre mot ait été entendu autour. Ces deux mots ne sont attendus qu'à ce moment-là, donc ça ne crée pas de déclenchement depuis la conversation.
3. **Un « iris annule » dit en retard, après « iris type », n'efface que la dictée.** Aujourd'hui, dans VS Code, il fait Ctrl+A puis Retour arrière : tout le champ est effacé. Ailleurs, « annule » garde son sens actuel.
4. **Plus de commandes se redisent sans « iris » pendant 2 s :** clic, suivant, précédent, espace et défile, en plus de skip, back, efface, undo et redo. Les journaux montrent 21 « iris clic » redits, ainsi que 6 « iris suivant » et 6 « iris espace ».
5. **Whisper est préparé dès que tu dis « iris type », « iris claude » ou « iris question »,** pendant que tu parles. On supprime ainsi les 1,5 à 3 s d'attente après les pauses de 10 min (120 fois dans les journaux). Il reste déchargé au repos, comme aujourd'hui.
6. **Journal fiable :** les mots jetés pendant une dictée sont notés « ignoré (dictée en cours) », au lieu de « acceptée » comme aujourd'hui. L'ouverture et la fin de chaque fenêtre de confirmation sont notées aussi.

## Lot 2 : reconnaissance des mots existants

- **skip et back sont rejetés à tort :** la deuxième vérification entend « skype » et « bac » (81 « skype » relevés). Ces formes confirmeront désormais skip et back.
- **« claude », « studio », « clic » et « souris » sont rejetés alors que le mot a bien été entendu** (11, 11, 8 et 7 fois). La deuxième vérification sera corrigée pour ces cas.

## Lot 3 : synonymes ajoutés (l'ancien mot reste)

| Mot actuel | Problème mesuré | Synonyme ajouté |
|---|---|---|
| pause | le plus pris dans la conversation : 127 fois | **suspends** |
| souris | 65 rejets, 14 « souris » puis « stop » | **pointeur** |
| colle / copie / coupe | « colle » : 67 pris dans la conversation contre 9 utilisés | **coller / copier / couper** |
| undo / redo | anglais ; « redo » absent du modèle | **défais / rétablis** |
| tab | 29 pris dans la conversation, certitude basse | **bascule** |
| lâche | 84 pris dans la conversation contre 12 utilisés | **relâche** |
| envoie | 105 pris dans la conversation | **valide** |
| défun / démute | morceaux « un », « des », « fun » entendus seuls (41 et 17 fois) | **sourdine** (déjà valable, jamais utilisé), **rallume** |
| plus tard | morceau « plus » entendu seul | **reporte** |
| haut / bas (Chrome, sans « iris ») | mots courants dans la conversation | **tout en haut / tout en bas** |

Mots qui ne changent pas : claude, studio, discord, chrome. Leurs rejets venaient de la vérification, pas du mot.

## Lot 4 : à décider par toi (retraits ou écoute par contexte)

- **Retirer des mots inutiles ?**
  - **wake** : 1 seule utilisation, 22 fois pris dans la conversation ; « réveil » fait la même chose.
  - **un mute** : morceau « un » entendu seul.
  - **ok** : jamais utilisé ; « merci » fait la même chose.
- **N'écouter les mots de souris que quand la souris est allumée (ou en Chrome) ?** Les mots concernés : clic, double, menu, glisse, lâche, défile. Aujourd'hui ils sont écoutés partout, et ils sont pris dans la conversation (clic 60 fois, menu 38, glisse 23). Il faudrait alors toujours dire « iris souris » avant un clic hors Chrome.
- **N'écouter les mots Discord que quand Discord est devant ?** Je ne le recommande pas : tu dis souvent « iris mute » depuis VS Code (56 fois).

## Ordre de travail

Une branche depuis `dev`. Les lots 1, 2 et 3 sont faits et testés un par un, avec le guide des commandes mis à jour. Le lot 4 attend ta décision.

Pour chaque mot touché, je cherche tous ses usages et j'écris un test par usage avant de modifier le code. Cas d'échec testés :
- « envoie » juste avant, pendant et juste après la fenêtre ;
- une dictée vide ;
- Whisper en échec ;
- un autre mot dit pendant la fenêtre.
