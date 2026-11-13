---
name: relancer
description: Arrêter proprement motionzero (Iris) puis le relancer en arrière-plan. Déclencheurs : /relancer, « relance l'appli », « relance Iris », appli fermée ou plantée.
---

1. Lancer `.venv/Scripts/pythonw.exe tools/relancer.pyw` (le raccourci « Iris » du bureau fait pareil) : il tue les
   instances `-m motionzero` (jamais le gardien `motionzero.garde`, jamais `/T` : ça tuerait Chrome, Discord, le bot),
   efface `logs/arret_voulu`, relance Iris et le gardien (qui s'arrête seul s'il tourne déjà).
   Arrêter Iris SANS relance (rare) : écrire d'abord `logs/arret_voulu`, sinon le gardien la relance sous 3 s.
2. Après ~5 s, lire la fin de `logs/motionzero.log` (et `logs/garde.log`) : signaler toute erreur, sinon dire en une ligne « Iris relancé ».
