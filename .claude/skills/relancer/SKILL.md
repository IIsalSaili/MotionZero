---
name: relancer
description: Arrêter proprement motionzero (Iris) puis le relancer en arrière-plan. Déclencheurs : /relancer, « relance l'appli », « relance Iris », appli fermée ou plantée.
---

1. Tuer toute instance : processus python/pythonw dont la ligne de commande contient `-m motionzero`.
   PowerShell : `Get-CimInstance Win32_Process | ? { $_.CommandLine -match '-m motionzero' } | % { taskkill /F /T /PID $_.ProcessId }`
2. Relancer en arrière-plan (run_in_background) : `.venv/Scripts/python -m motionzero --voice`.
3. Après ~5 s, lire la fin du dernier fichier de `logs/` : signaler toute erreur, sinon dire en une ligne « Iris relancé ».
