"""Raccourci « Iris » du bureau : arrête l'instance en cours (s'il y en a une) puis relance Iris.
Sans fenêtre (pythonw). Tue seulement les processus « -m motionzero », jamais leurs enfants (pas de /T :
ce serait fermer Chrome, le bot Discord…)."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHONW = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
NO_WINDOW = 0x08000000

ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*-m motionzero*' -and "
      "$_.ProcessId -ne %d } | ForEach-Object { $_.ProcessId }" % os.getpid())
out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                     creationflags=NO_WINDOW).stdout
for pid in out.split():
    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, creationflags=NO_WINDOW)

subprocess.Popen([PYTHONW, "-m", "motionzero", "--voice"], cwd=ROOT, creationflags=NO_WINDOW)
sys.exit(0)
