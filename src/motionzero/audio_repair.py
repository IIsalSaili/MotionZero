"""Réparer le son sans redémarrer le PC (bouton tout en bas à gauche, jamais automatique).

Constaté le 12/11/2026 : le micro du casque s'est figé (plus aucun son transmis, même débranché puis rebranché) ;
le moteur audio de Windows (audiodg.exe) le tenait. Redémarrer les services audio suffit.
Il faut les droits administrateur : Windows affiche sa fenêtre « Oui / Non » à chaque réparation (choix de
l'utilisateur : pas de tâche préparée avec les droits administrateur).
"""
import logging
import subprocess
import time

log = logging.getLogger("motionzero.audio_repair")

NO_WINDOW = 0x08000000
# Audiosrv dépend d'AudioEndpointBuilder : on arrête le premier, redémarre le second, relance le premier
SCRIPT = "Stop-Service Audiosrv -Force; Restart-Service AudioEndpointBuilder -Force; Start-Service Audiosrv"
ELEVATE = ("try { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
           f"-ArgumentList '-NoProfile','-Command','{SCRIPT}'; exit 0 }} catch {{ exit 5 }}")


def _run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def _service_running(name) -> bool:
    try:
        return "RUNNING" in _run(["sc", "query", name], timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False


def repair(reopen, heard_since, wait=time.sleep, clock=time.perf_counter) -> str:
    """Redémarre le son (fenêtre administrateur « Oui ») puis rouvre le micro d'Iris. Renvoie le message
    pour l'île. reopen() : rouvre le micro ; heard_since(t) : vrai si du son est arrivé depuis t."""
    log.info("reparation du son demandee")
    try:
        done = _run(["powershell", "-NoProfile", "-Command", ELEVATE], timeout=180)
    except (OSError, subprocess.SubprocessError):
        log.exception("lancement de la reparation")
        return "REPARATION DU SON : ECHEC DU LANCEMENT"
    if done.returncode != 0:                    # « Non » sur la fenêtre de Windows, ou fermée
        return "REPARATION DU SON ANNULEE"
    for _ in range(20):                         # le service repart (quelques secondes au plus)
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
