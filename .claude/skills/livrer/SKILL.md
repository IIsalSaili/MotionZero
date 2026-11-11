---
name: livrer
description: Livrer la branche temporaire courante dans dev après validation de l'utilisateur (tests, fusion, nettoyage, issue).
---

L'utilisateur ne peut pas taper : Claude lance ce skill quand l'utilisateur valide (oralement ou par écrit) la fusion. Étapes, s'arrêter et expliquer au premier échec :
1. Vérifier qu'on est sur une branche temporaire (ni `dev` ni `main`) et que l'arbre est propre ; sinon committer le travail (message français court, sans mention de Claude).
2. `.venv/Scripts/python -m pytest -q` : doit passer.
3. `git push` de la branche, puis `git checkout dev && git pull && git merge --no-ff <branche> -m "Fusion <branche> : <résumé>"` et `git push`.
4. Vérifier `git merge-base --is-ancestor <branche> dev`, puis supprimer la branche : `git branch -d <branche>` et `git push origin --delete <branche>`.
5. Issues GitHub liées (`gh issue list`) : commenter ou fermer celles réglées ; créer une issue pour tout point reporté (sans mention de Claude).
6. Relancer motionzero (skill relancer) si du code de l'appli a changé.
7. Résumé en 2-3 lignes : ce qui est fusionné, issues touchées.
