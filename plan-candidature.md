# Plan : rendre le mode candidature utilisable en vrai

Audit du 21/11/2026 de `src/motionzero/cvgen.py`. Le tri et la préparation tiennent ; postuler sur le site reste théorique.
Chaque point a son issue GitHub (étiquette `candidature`).

## Étape 1 : ne plus perdre ni casser d'offre
- Offre gardée invisible tant que son CV se génère : le message « verdict » la retire, `a_parcourir` ignore l'état « gardée ».
- Aucune annulation : un « écarte » ou « postulé » mal entendu est définitif. Ajouter « annule » (dernier verdict).

## Étape 2 : remplir un formulaire vite et sans risque
- Vérifier que la fenêtre au premier plan est le navigateur avant de taper ; sinon le dire.
- Profil lu une fois à l'ouverture du mode (pas à chaque champ).
- Mot pour passer au champ suivant (Tab), puis « remplis » : libellés des champs lus dans la page, remplis d'un coup.
- Champs manquants : adresse, code postal, pays, date de naissance, disponibilité, salaire, permis.
- Questions libres : issue #46 (déjà ouverte).

## Étape 3 : les vrais sites
- Tester les 3-4 sites réellement utilisés : zones de dépôt, CV repris, formulaires en plusieurs pages.
- Connexion / création de compte avant de postuler.

## Étape 4 : suivi et robustesse
- Liste des candidatures envoyées et des relances dues (J+7).
- État (liste, préparation, PDF) gardé après une relance d'Iris ; fin du suivi à 15 min annoncée.
- « prépare tout » : file d'attente des offres gardées.

## Étape 5 : confort
- Interface dédiée au mode (grand panneau comme le calendrier) : maquettes dans l'artefact « Iris candidature : maquettes ».
- Carte plus riche : ville, télétravail, contrat, salaire, date.
- Fin de liste annoncée au lieu de repartir au début en silence.
- « répète » : réafficher la carte.
- Mots courts confondus (« cv », « nom »/« prénom », « lien »/« liste ») : mesurer sur enregistrements.
