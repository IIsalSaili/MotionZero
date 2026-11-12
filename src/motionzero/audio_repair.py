"""Réparer le son sans redémarrer le PC (bouton tout en bas à gauche, jamais automatique).

Constaté le 12/11/2026 : le micro du casque s'est figé (plus aucun son transmis, même débranché puis rebranché) ;
le moteur audio de Windows (audiodg.exe) le tenait. Redémarrer les services audio suffit.
Il faut les droits administrateur : une tâche Windows « Iris - reparer le son » est créée UNE fois (une fenêtre
« Oui » à valider), à son nom et « avec les privilèges les plus élevés » ; la lancer ensuite ne demande plus rien.
"""
import logging
import subprocess
import time

log = logging.getLogger("motionzero.audio_repair")

TASK = "Iris - reparer le son"
NO_WINDOW = 0x08000000
# Audiosrv dépend d'AudioEndpointBuilder : on arrête le premier, redémarre le second, relance le premier
SCRIPT = ("Stop-Service Audiosrv -Force; Restart-Service AudioEndpointBuilder -Force; Start-Service Audiosrv")


def _run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def installed() -> bool:
    try:
        return _run(["schtasks", "/query", "/tn", TASK]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install() -> bool:
    """Crée la tâche (fenêtre administrateur à valider une fois). Vrai si elle existe ensuite."""
    import getpass
    import os
    import tempfile
    user = getpass.getuser()
    body = (f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "
            f"'-NoProfile -WindowStyle Hidden -Command \"{SCRIPT}\"'\n"
            f"$p = New-ScheduledTaskPrincipal -UserId '{user}' -RunLevel Highest -LogonType Interactive\n"
            "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2)\n"
            f"Register-ScheduledTask -TaskName '{TASK}' -Action $a -Principal $p -Settings $s -Force\n")
    path = os.path.join(tempfile.gettempdir(), "iris_installe_reparation.ps1")
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(body)
        _run(["powershell", "-NoProfile", "-Command",
              "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
              f"'-NoProfile','-ExecutionPolicy','Bypass','-File','{path}'"], timeout=180)
    except (OSError, subprocess.SubprocessError):
        log.exception("creation de la tache de reparation")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return installed()


def _service_running(name) -> bool:
    try:
        return "RUNNING" in _run(["sc", "query", name], timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False


def repair(reopen, heard_since, wait=time.sleep, clock=time.perf_counter) -> str:
    """Redémarre le son puis rouvre le micro d'Iris. Renvoie le message pour l'île.
    reopen() : rouvre le micro ; heard_since(t) : vrai si du son est arrivé depuis t."""
    if not installed():
        return "REPARATION DU SON NON INSTALLEE"
    log.info("reparation du son demandee")
    try:
        if _run(["schtasks", "/run", "/tn", TASK]).returncode != 0:
            return "REPARATION DU SON : ECHEC DU LANCEMENT"
    except (OSError, subprocess.SubprocessError):
        log.exception("lancement de la reparation")
        return "REPARATION DU SON : ECHEC DU LANCEMENT"
    wait(2.0)                                   # le service s'arrête
    for _ in range(20):                         # puis repart (quelques secondes au plus)
        if _service_running("Audiosrv"):
            break
        wait(0.5)
    else:
        return "SERVICE AUDIO NON REDEMARRE"
    wait(1.0)
    t0 = clock()
    try:
        reopen()
    except Exception:
        log.exception("reouverture du micro")
        return "MICRO NON ROUVERT : relance Iris"
    for _ in range(10):
        if heard_since(t0):
            log.info("son repare, micro rouvert")
            return "SON REPARE"
        wait(0.3)
    return "MICRO TOUJOURS MUET"
