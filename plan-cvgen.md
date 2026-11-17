# Plan : CVGEN piloté entièrement par Iris

But : faire tout le parcours d'une candidature sans mains ni clavier, depuis Iris (voix + tête),
de « cherche des offres » jusqu'à « candidature envoyée », puis le suivi (relances, entretiens).

## 1. Point de départ

### Ce que CVGEN sait déjà faire seul
- **Trouver des offres** : agent de recherche (`POST /api/agent/demarrer`, `/arreter`) + extension Chrome
  qui capture les pages. Tourne en continu jusqu'à l'arrêt.
- **Trier** : chaque offre reçoit une note sur cinq axes ; les mauvaises sont écartées.
- **Brouillon du CV** : automatique pour chaque offre gardée (Qwen local).
- **CV final** : « Composer avec Claude » (`POST /api/generations/:id/regenerer`, `mode: "claude"`).
- **Pièces prêtes** : `POST /api/offres/:id/preparer` (CV, lettre, etc.), puis `en-cours` range les PDF
  dans un dossier fixe et renvoie leurs chemins.
- **Suivi** : `POST /api/postulees`, relances à J+7, entretiens (`PATCH /api/postulees/:id`).

Tout est exposé par l'API locale `http://127.0.0.1:3000` : Iris peut tout piloter **sans clic ni touche**,
comme elle le fait déjà avec VS Code par `pont.py`.

### Ce qui demande encore les mains aujourd'hui
| Étape | Aujourd'hui | Difficulté |
|---|---|---|
| Lancer CVGEN | `lancer.bat` | facile |
| Lancer / arrêter la recherche | bouton | facile (API) |
| Parcourir les offres à vérifier | lecture + clics | moyenne : il faut une présentation à la voix |
| Garder / écarter une offre | bouton | facile (API) |
| Relire et corriger le CV | atelier, édition au clavier | moyenne |
| Composer, préparer, exporter | boutons | facile (API) |
| **Déposer la candidature sur le site** | formulaire du site, « Choisir un fichier », Ctrl+V | **difficile** : chaque site est différent |
| Noter « j'ai postulé », relances, entretiens | boutons | facile (API) |

Le vrai sujet est le dépôt sur le site. Le reste est un travail de branchement.

## 2. Principes (repris des règles d'Iris)

- **Zéro modification de CVGEN** (décidé le 17/11) : tout le travail est dans Iris. Iris appelle les
  adresses que les boutons de CVGEN appellent déjà ; pour CVGEN, c'est comme si tu avais cliqué.
  Ni raccourcis clavier ajoutés, ni nouvelle route, ni nouveau mode côté CVGEN.

- **Rien d'irréversible sans « envoie »** : garder une offre, lancer une composition, déposer une
  candidature. Sans « envoie » dans les 10 s : annulé, jamais lancé seul.
- **Pas de touches simulées pour CVGEN** : Iris parle à l'API.
- **Iris parle en son nom** : jamais « Claude » ni « Haiku » dans ce qu'elle dit ou affiche
  (« Iris compose le CV », pas « Claude compose »).
- **Core jamais touché depuis un autre fil** : les appels HTTP tournent dans un fil, les résultats
  passent par une queue lue dans la boucle principale (même schéma qu'`instruction.py`).
- **Échecs prévus et testés** : CVGEN éteint, offre introuvable, « Claude occupé » (409), brouillon pas
  prêt (409), PDF absent (404), Ollama injoignable, rien entendu.
- **Un mode dédié « iris candidature »** (décidé le 17/11) : s'ouvre et se ferme en redisant son nom.
  Ses mots ne sont guettés **que dans ce mode**, pour ne pas ajouter de mots à la reconnaissance de base :
  hors du mode, Whisper ne voit aucun mot de plus. Dans le mode, la liste des mots attendus est courte
  et donnée à Whisper comme indice (comme pour les autres modes), les mots de base restant actifs.
- **Rien d'automatisé sur les sites d'emploi** (décidé le 17/11) : aucun clic, aucun remplissage, aucun
  envoi fait par un programme sur la page d'un site. Ces sites détectent l'automatisation et peuvent
  bloquer le compte. Le dépôt se fait par toi, avec les outils habituels d'Iris (curseur à la tête,
  clic par geste ou à la voix, dictée), comme pour n'importe quel autre site.

## 3. Architecture

```
Voix (Whisper) ──> Iris : mode « candidature »
                     │
                     ├── cvgen.py   client HTTP de l'API CVGEN (fil + queue)
                     ├── île / cartes : offre courante, score, état, pièces prêtes
                     └── tête : défiler l'aperçu du CV, oui / non
                     │
                     v
              CVGEN 127.0.0.1:3000 ──> Qwen local, composition, PDF
                     │
                     v
        Dépôt sur le site : par toi, avec le curseur d'Iris (phase 4)
```

Nouveau module `src/motionzero/cvgen.py` :
- `etat()` (`/api/health` + `/api/agent` + `/api/preparation`) : CVGEN joignable, recherche en cours,
  préparation en cours.
- `a_verifier()` : offres « à vérifier », triées par note.
- `garder(id)`, `ecarter(id)`, `composer(cv_id)`, `preparer(id)`, `en_cours(id)`, `postule(id)`.
- Toute erreur renvoie un message court à afficher (« CVGEN est éteint », « Une autre candidature
  est en préparation »), jamais une exception qui remonte.

Démarrage : si CVGEN ne répond pas, Iris lance `node server.mjs` caché (`pythonw` / `CREATE_NO_WINDOW`),
comme le gardien relance Iris.

## 4. Les phases

Chaque phase = une branche depuis `dev`, testée, validée par toi, fusionnée avant la suivante.

### Phase 1 : piloter CVGEN à la voix (le socle)
Commandes, dans le mode « iris candidature » :
- « cherche des offres » / « arrête la recherche »
- « combien d'offres » → « 4 offres à vérifier, 2 nouvelles depuis ce matin »
- « état » → recherche en cours ou non, préparation en cours, dernière erreur
- « ouvre CVGEN » (page Offres dans Chrome)

Tests : CVGEN éteint, agent déjà lancé, recherche arrêtée seule (site bloqué).
**Résultat** : la recherche tourne et se surveille sans toucher le clavier.

### Phase 2 : trier les offres à la voix
Iris présente **une offre à la fois** sur une carte : poste, entreprise, ville, note, deux ou trois
points forts et le point faible principal.
- « suivante » / « précédente » (ou un mouvement de tête)
- « garde » → brouillon du CV lancé ; « écarte » → offre écartée
- « ouvre l'offre » → la page du site dans Chrome

Tests : liste vide, offre disparue entre-temps, double « garde ».
**Résultat** : le tri d'une journée d'offres se fait de la voix et de la tête.

### Phase 3 : CV et pièces prêtes, sans clavier
- « compose le CV » (+ « envoie ») → composition lancée, carte « Iris compose… » puis « CV prêt »
- « montre le CV » → aperçu PDF ; la tête fait défiler
- « refais la ligne 3 », « annule la ligne 3 » → `POST /api/claude/ligne`, `precedent`
- « fais relire » → jury ; Iris annonce le nombre de corrections proposées, « accepte » / « refuse »
  une par une
- « prépare la candidature » → CV + lettre en PDF dans le dossier fixe

Tests : brouillon pas prêt (409), composition déjà en cours (409), PDF absent (404), composition qui échoue.
**Résultat** : tout ce qui se passe dans CVGEN se fait à la voix. Il ne reste que le site.

### Phase 4 : déposer la candidature sur le site, sans automatisation
Aucun programme n'agit sur la page du site : c'est toi qui cliques, avec le curseur à la tête et le clic
d'Iris, exactement comme sur n'importe quel site aujourd'hui. Pour le site, ce sont des gestes humains,
à vitesse humaine. Iris ne fait que **préparer** et **mettre sous la main** :

- **Ouvrir la bonne page** : « postule » ouvre l'offre dans Chrome (lien gardé par CVGEN), comme
  « ouvre l'offre ». C'est l'équivalent de cliquer un lien : rien d'automatisé sur le site.
- **Pièces prêtes** : `en-cours` range le CV et la lettre dans le dossier fixe. Dans la fenêtre
  « Choisir un fichier », tu dis « colle le CV » : Iris met le chemin dans le presse-papiers et le
  colle dans cette fenêtre, qui est une fenêtre de Windows, pas la page du site.
- **Textes prêts à coller** : nom, mail, téléphone, LinkedIn sont lus dans le profil de CVGEN
  (`GET /api/profile`, celui qui sert déjà au CV), au moment où tu les demandes. Rien n'est recopié ni
  enregistré dans Iris : si tu changes ton numéro dans CVGEN, Iris colle le nouveau. Tu cliques dans
  le champ, tu dis « colle le mail » : Iris colle **ce seul champ, quand tu le demandes**, comme la
  dictée que tu utilises déjà partout. Le chemin du CV vient de `en-cours` (dossier fixe de CVGEN).
- **Questions libres du formulaire** : « réponds à : pourquoi notre entreprise » → Iris envoie la
  question avec l'offre et le profil à la route existante `POST /api/llm` (le modèle local de CVGEN) ;
  la réponse courte est affichée sur la carte ; tu la relis puis « colle-la ».
- **Clic final « Envoyer »** : toujours toi.
- **Après l'envoi** : « c'est envoyé » → CVGEN marque l'offre « postulée » (relance à J+7).

Pourquoi c'est sûr : aucune extension ne remplit la page, aucun agent n'y navigue, aucun clic n'est
fait à ta place. Coller dans un champ que tu as choisi, au moment où tu le demandes, est ce que fait
n'importe quel humain.

Cas à part, **les offres « postuler par e-mail »** : Iris construit elle-même un
brouillon `.eml` (adresse de l'offre, objet, texte court, CV et lettre en pièces jointes depuis le
dossier de `en-cours`) et l'ouvre dans ton client mail. Tu
relis, tu cliques « Envoyer ». Pas de site d'emploi dans la boucle.

Tests : offre sans lien, PDF absent au moment de « colle le CV », presse-papiers occupé, fenêtre
« Choisir un fichier » pas au premier plan, rien entendu, champ demandé inconnu (« colle le fax »).

**À noter** : l'agent de recherche actuel de CVGEN navigue déjà sur les sites d'emploi de façon
automatique. Le même risque de blocage existe donc déjà pour la recherche. À surveiller : si un site
bloque, CVGEN s'arrête déjà seul (README) ; ce plan n'y ajoute rien.

### Phase 5 : le suivi
- « j'ai postulé » (si dépôt hors Iris) → `POST /api/postulees`
- Iris annonce le matin les relances dues et les entretiens du jour (lien avec `reminders.py` et le
  calendrier d'Iris)
- « note un entretien avec X mardi à 14 h » → candidature passée en « entretien » + rappel Iris
- « refusé pour X » → état mis à jour
- « prépare l'entretien X » → questions probables lues une à une

### Phase 6 : la file du jour (dans Iris, avec les adresses existantes)
« iris candidature automatique » : Iris enchaîne elle-même les appels que tu ferais à la main dans
CVGEN : lancer la recherche (`/api/agent/demarrer`), lister les offres gardées par CVGEN, composer
(`regenerer`), préparer (`preparer`, `en-cours`). Elle tient sa propre file « prêtes à envoyer »
(un petit fichier dans `logs/` d'Iris, reconstruit depuis CVGEN au démarrage).

Iris ne décide rien sur les offres : elle reprend celles que CVGEN a déjà gardées selon ses critères.
Ensuite : « 5 candidatures prêtes » ; « postule » ouvre la première, tu colles et tu envoies,
« c'est envoyé », « suivante ».

Tests : CVGEN fermé en cours de route, composition refusée (409), file vide, relance d'Iris au milieu
(la file se reconstruit sans doublon).

## 5. Points d'attention

- **Carte graphique** : Whisper + Qwen 4B (instruction) + Qwen 8B (CVGEN) en même temps. Pas bloquant
  (pendant une session de candidatures, rien d'autre ne tourne), à surveiller seulement si ça rame.
- **Abonnement** : seul le jury consomme vraiment ; la composition presque rien. Iris prévient
  seulement avant un jury.
- **Comptes sur les sites** : connexion faite une fois, puis gardée par Chrome.
- **CVGEN garde son principe** « rien n'agit sur le site » : ce plan le respecte.
- **Adresses de CVGEN qui changent** : Iris dépend d'elles sans que CVGEN le sache. `cvgen.py` les
  regroupe toutes au même endroit, et un test vérifie qu'elles existent encore dans `server.mjs`.

## 6. Estimation (avec Claude)

| Phase | Taille |
|---|---|
| 1. Mode candidature + pilotage | ~1 séance |
| 2. Tri des offres | ~1 à 2 séances |
| 3. CV et pièces | ~2 séances |
| 4. Dépôt : coller, réponses, e-mail | ~2 séances |
| 5. Suivi | ~1 séance |
| 6. File du jour | ~1 séance |
