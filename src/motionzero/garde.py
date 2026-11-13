"""Gardien d'Iris : la relance si elle plante ou se fige, sans dépendre du bot Discord.

Lancé sans fenêtre au démarrage de Windows (`pythonw -m motionzero.garde --start`) et par le raccourci « Iris ».
- Iris écrit toutes les 2 s un battement (logs/battement.json : pid, heure, âge de la boucle principale).
- STOP (arrêt voulu) écrit logs/arret_voulu : le gardien ne relance pas.
- Iris absente sans arrêt voulu, ou boucle figée depuis FREEZE_S : relance (on tue seulement son pid, jamais /T).
- Trop de relances rapprochées (MAX_RESTARTS en WINDOW_S) : le gardien abandonne et l'écrit au journal,
  pour ne pas tourner en boucle sur un plantage au démarrage.
- Le bot Discord relance aussi Iris : avant de relancer, on vérifie qu'aucune instance ne tourne déjà.
"""
import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BEAT_FILE = os.path.join(ROOT, "logs", "battement.json")
STOP_FILE = os.path.join(ROOT, "logs", "arret_voulu")
PYTHONW = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
NO_WINDOW = 0x08000000

PERIOD_S = 3.0
BEAT_STALE_S = 20.0     # plus de battement depuis 20 s : processus mort ou figé tout entier
FREEZE_S = 60.0         # boucle principale muette depuis 60 s (le fil du battement, lui, vit encore)
LAUNCH_GRACE_S = 45.0   # après un lancement : le temps que les modèles se chargent
MAX_RESTARTS = 3
WINDOW_S = 180.0

log = logging.getLogger("motionzero.garde")


# --- côté Iris -----------------------------------------------------------------------------------------------

def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_beat(loop_age, path=BEAT_FILE, pid=None, now=None):
    try:
        _write_atomic(path, json.dumps({"pid": pid or os.getpid(), "t": now or time.time(),
                                        "loop_age": round(loop_age, 1)}))
    except OSError:
        log.debug("battement non ecrit", exc_info=True)


def run_beat(live, stop, period_s=2.0, clock=time.perf_counter):
    """Fil « battement » d'Iris. live["beat"] = dernier tour de la boucle principale (perf_counter)."""
    clear_stop()
    while not stop.wait(period_s):
        beat = live.get("beat")
        write_beat(0.0 if beat is None else clock() - beat)


def mark_stop(path=STOP_FILE):
    """Arrêt voulu (STOP) : pas de relance."""
    try:
        _write_atomic(path, str(time.time()))
    except OSError:
        log.warning("arret voulu non note", exc_info=True)


def clear_stop(path=STOP_FILE):
    try:
        os.remove(path)
    except OSError:
        pass


# --- côté gardien --------------------------------------------------------------------------------------------

def read_beat(path=BEAT_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and "pid" in data and "t" in data else None
    except (OSError, ValueError):
        return None


def decide(beat, stopped, alive, now, last_launch):
    """Que faire maintenant ? -> "rien", "lance" ou "tue" (tuer le pid figé puis relancer). Pur : testable.
    beat : dernier battement (ou None) ; stopped : arrêt voulu noté ; alive(pid) -> bool."""
    if last_launch is not None and now - last_launch < LAUNCH_GRACE_S:
        return "rien"
    if stopped:
        return "rien"
    if beat is None:
        return "lance"
    if not alive(beat["pid"]):
        return "lance"
    if now - beat["t"] > BEAT_STALE_S or beat.get("loop_age", 0) > FREEZE_S:
        return "tue"
    return "rien"


def too_many(launches, now):
    return len([t for t in launches if now - t < WINDOW_S]) >= MAX_RESTARTS


def pid_alive(pid):
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == 259          # STILL_ACTIVE


def iris_pids():
    """Pids des processus « -m motionzero » (sans le gardien lui-même)."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*-m motionzero*' -and "
          "$_.CommandLine -notlike '*motionzero.garde*' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        log.warning("liste des processus impossible", exc_info=True)
        return []
    return [int(p) for p in out.split() if p.isdigit()]


def launch():
    subprocess.Popen([PYTHONW, "-m", "motionzero", "--voice"], cwd=ROOT, creationflags=NO_WINDOW)


def kill(pid):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)


def _single_instance():
    if sys.platform != "win32":
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, "Local\\iris_garde")
    return ctypes.get_last_error() != 183           # ERROR_ALREADY_EXISTS


def main(argv=None):
    ap = argparse.ArgumentParser(prog="motionzero.garde")
    ap.add_argument("--start", action="store_true", help="lance Iris tout de suite si elle ne tourne pas")
    args = ap.parse_args(argv)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    logging.basicConfig(filename=os.path.join(ROOT, "logs", "garde.log"), level=logging.INFO,
                        format="%(asctime)s %(message)s", encoding="utf-8")
    if not _single_instance():
        return                                       # un gardien tourne déjà
    log.info("gardien demarre")
    launches, last_launch = [], None
    if args.start and not iris_pids():
        clear_stop()
        launch()
        last_launch = time.time()
        log.info("Iris lancee au demarrage")
    while True:
        time.sleep(PERIOD_S)
        now = time.time()
        what = decide(read_beat(), os.path.exists(STOP_FILE), pid_alive, now, last_launch)
        if what == "rien":
            continue
        if too_many(launches, now):
            log.error("%d relances en %.0f s : le gardien abandonne", MAX_RESTARTS, WINDOW_S)
            return
        if what == "tue":
            beat = read_beat()
            if beat and beat["pid"] in iris_pids():  # jamais tuer un pid réutilisé par un autre programme
                log.warning("Iris figee (pid %s) : arret force", beat["pid"])
                kill(beat["pid"])
                time.sleep(2)
        elif iris_pids():                            # relancée entre-temps (bot Discord, raccourci)
            last_launch = now
            continue
        log.warning("Iris absente sans arret voulu : relance")
        launch()
        last_launch = now
        launches.append(now)


if __name__ == "__main__":
    main()
