# Plan : refonte de la logique des modes

Étude du 14/11/2026 : code (core.py, app.py, vscode.py), journaux du 10 au 14/11 (68 000 lignes), historique git, issues.

## Le constat

**Le mode Chrome s'allume à la voix, mais s'éteint tout seul** dès que Chrome n'est plus la fenêtre au premier plan (contrôle toutes les 0,3 s, `core.chrome_front`). Or Iris met elle-même d'autres fenêtres devant :

| Commande | Ce qu'Iris fait en coulisses | Résultat |
|---|---|---|
| mute, démute, défun | met sa fenêtre invisible devant pour taper le raccourci Discord, sans rendre la main à Chrome (`vscode.py:133`) | Chrome quitté en 0,3 s |
| claude, annule | met VS Code devant | Chrome quitté |
| accueil, aide, guide | ouvre une fenêtre d'Iris ou le navigateur | Chrome quitté |
| tab, ouvre | autre appli devant | Chrome quitté (normal) |

Pour VS Code, ce cas est déjà toléré (`app.py:900`) ; pour Chrome, non.

Dans les journaux, en 4 jours :
- 63 sorties du mode Chrome ;
- **53 fois, tu as redit « iris chrome » moins de 30 s après**.

Causes des sorties absurdes :

| Cause | Nombre |
|---|---|
| mute, démute, défun | 5 |
| « stop » dit pour faire taire un rappel, qui fait aussi sortir de Chrome | 3 |
| « pause » puis « reprise », qui ramène toujours au neutre | 7 |
| Chrome pas reconnu juste après « iris chrome », retombé au neutre 4 s plus tard sans rien dire (3 fois de suite le 12/11 à 19:37) | 7 |
| « iris claude » | 5 |

Autres incohérences relevées :
- « stop » ne marche pas pendant une dictée, alors qu'il est censé passer avant tout (`core.py:550`) ;
- il faut parfois deux « stop » : le premier éteint la souris, le second quitte Chrome ;
- « ferme » a quatre sens selon le contexte ;
- la lecture ne se quitte jamais toute seule ;
- la pause n'efface ni le calendrier ni la répétition ;
- le journal dit « mode NEUTRE » sans dire pourquoi.

## Le principe proposé

> **Le mode suit l'appli que tu regardes, pas les fenêtres qu'Iris ouvre en coulisses. Une commande qui ne parle pas de changer d'appli ou de mode ne change jamais le mode.**

Concrètement :

1. **Les fenêtres d'Iris ne comptent pas.** La fenêtre invisible pour Discord, l'accueil, l'aide, le calendrier et la réponse ne font jamais quitter un mode. Et après un raccourci Discord, Iris rend la main à la fenêtre d'avant : Chrome garde aussi le clavier, et « skip » marche juste après « mute ».
2. **Le mode Chrome suit Chrome, automatiquement** (choix A ci-dessous) : Chrome devant, ce sont les mots Chrome ; une autre appli à toi devant, c'est le neutre. Plus besoin de dire « iris chrome » ; la commande reste valable, elle met Chrome devant. Il n'y a pas d'état caché : le mode affiché est toujours celui de la fenêtre que tu vois. C'est déjà ainsi que marche « suivant / précédent » dans VS Code.
3. **« stop » arrête d'abord ce qui est en cours,** dans cet ordre : son, alarme ou rappel, puis dictée ou question, puis défilement, puis souris, puis le mode. Un seul « stop » par chose, et il marche aussi pendant une dictée.
4. **La pause ne fait pas oublier le mode.** Avec le choix A, « iris reprise » retrouve le mode de l'appli devant ; sinon, il revient au mode d'avant la pause, qui reste affiché pendant la pause (« PAUSE (CHROME) »). La pause ferme aussi le calendrier et l'aide.
5. **Plus de sortie silencieuse.** Si « iris chrome » ne trouve pas Chrome, l'île le dit (« CHROME INTROUVABLE ») au lieu de retomber au neutre sans rien dire.
6. **Chaque changement de mode est noté avec sa cause** dans le journal (« Chrome plus devant : Discord.exe », « stop », « pause »). On pourra compter les sorties avant et après.
7. **Aucun usage retiré.** Tous les mots gardent leur sens actuel dans chaque mode : ferme, agrandis / réduis, suivant / précédent, skip / back / espace sans « iris ». Un test par sens, écrit avant la modification.

Ce qui ne change pas :
- le neutre par défaut ;
- la souris, qui reste un outil à part et pas un mode ;
- les clics à la voix ;
- seul « iris reprise » quitte la pause ;
- aucun geste en Chrome.

## Les choix à faire

- **A. Le mode Chrome automatique (recommandé).** Chrome devant suffit, plus besoin de dire « iris chrome ». C'est ce qui supprime les 53 redites. Le risque connu, déjà relevé au check-up du 13/11 : en Chrome, 17 mots courants marchent sans « iris » (« retour », « bas », « ferme »…), donc dès que Chrome est devant, une conversation peut déclencher une commande. Tu le vivais déjà en mode Chrome ; avec A, ce sera le cas chaque fois que Chrome est devant.
  - **Variante A'** : entrée automatique, mais les mots sans « iris » restent coupés tant que tu n'as pas dit « iris chrome » une fois depuis que Chrome est passé devant.
- **B. Le mode Chrome reste déclaré à la voix,** mais il ne s'arrête plus que si une de tes applis à toi passe devant (fenêtres d'Iris ignorées), ou sur « stop », un autre mode, « studio » ou « discord ». C'est la correction minimale.
- **C. La lecture** : la garder telle quelle, déclarée à la voix et quittée par « stop » (peu utilisée depuis le 10/11), ou la lier elle aussi aux applis de lecture.

## Les étapes

Une seule branche depuis `dev`, en lots testés un par un :

1. **Correctif immédiat :**
   - les fenêtres d'Iris ne font plus quitter Chrome ;
   - le raccourci Discord rend la main à la fenêtre d'avant.

   Tests : « mute » ou « démute » en Chrome, accueil, aide et calendrier ouverts depuis Chrome, puis vérifier que Chrome garde le clavier (« skip » juste après « mute »).
2. **Journal des changements de mode avec leur cause,** et message à l'écran si Chrome est introuvable.
3. **« stop » par ordre de priorité,** et « stop » qui marche pendant une dictée.
4. **La pause qui garde le mode,** et qui ferme le calendrier et l'aide.
5. **Choix A, A' ou B.**
6. **Mesure :** une soirée d'usage, puis recompter dans le journal les sorties de mode et les redites de « iris chrome ».

Cas d'échec à tester à chaque lot :
- Chrome fermé alors que le mode Chrome est actif ;
- Chrome réduit ;
- deux fenêtres Chrome ;
- Discord absent ;
- raccourci Discord non réglé ;
- fenêtre d'avant disparue au moment de lui rendre la main ;
- « stop » quand rien n'est en cours.
