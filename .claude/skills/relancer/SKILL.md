---
name: relancer
description: Arrêter proprement motionzero (Iris) puis le relancer en arrière-plan. Déclencheurs : /relancer, « relance l'appli », « relance Iris », appli fermée ou plantée.
---

1. Tuer toute instance : processus python/pythonw dont la ligne de commande contient `-m motionzero`.
   PowerShell : `Get-CimInstance Win32_Process | ? { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match '-m motionzero' } | % { taskkill /F /PID $_.ProcessId 2>$null }`
   (Filtrer sur le nom : sans ça, le shell qui lance la commande se tue lui-même. Iris = 2 processus python, lanceur du venv + enfant : normal, les deux sont visés.)
   JAMAIS `/T` : il tue tout l'arbre, donc les applis ouvertes par Iris (Chrome, Discord…) et le bot Discord.
2. Relancer en arrière-plan (run_in_background) : `.venv/Scripts/python -m motionzero --voice`.
3. Après ~5 s, lire la fin du dernier fichier de `logs/` : signaler toute erreur, sinon dire en une ligne « Iris relancé ».
