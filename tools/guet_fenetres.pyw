"""Surveillance permanente des programmes lancés sur le PC (fenêtres de console qui clignotent).

Tourne sans fenêtre (pythonw), lancé au démarrage de Windows (raccourci « Guet fenêtres » du dossier Démarrage).
Chaque nouveau programme est noté dans logs/fenetres.log avec ses parents (qui l'a lancé), sauf le bruit
habituel (Chrome, services Windows). Le fichier est tourné à 5 Mo (un seul ancien gardé : fenetres.log.1).
Une seule instance : une deuxième s'arrête tout de suite.
"""
import os
import socket
import sys
import time

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "fenetres.log")
MAX_BYTES = 5_000_000
POLL_S = 0.1
NOISE = {"chrome.exe", "msedge.exe", "msedgewebview2.exe", "svchost.exe", "searchprotocolhost.exe",
         "searchfilterhost.exe", "runtimebroker.exe", "backgroundtaskhost.exe", "dllhost.exe", "wmiprvse.exe",
         "smartscreen.exe", "taskhostw.exe", "audiodg.exe", "code.exe", "discord.exe"}
LOCK_PORT = 47899          # port local tenu tant que le guet tourne : empêche deux instances


def describe(pid):
    try:
        p = psutil.Process(pid)
        return p.name(), " ".join(p.cmdline())[:300], p.ppid()
    except (psutil.Error, OSError):
        return None, "", None


def chain(ppid, depth=3):
    out = []
    while ppid and depth:
        name, cmd, ppid = describe(ppid)
        if name is None:
            out.append("(terminé)")
            break
        out.append(f"{name} [{cmd[:150]}]")
        depth -= 1
    return " <- ".join(out)


def write(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    try:
        if os.path.getsize(LOG) > MAX_BYTES:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        sys.exit(0)                      # déjà lancé
    write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} guet démarré")
    seen = set(psutil.pids())
    while True:
        time.sleep(POLL_S)
        try:
            now = set(psutil.pids())
        except OSError:
            continue
        for pid in now - seen:
            name, cmd, ppid = describe(pid)
            if name is None:
                name, cmd = "(déjà terminé)", ""
            if name.lower() in NOISE:
                continue
            write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {name} {pid} :: {cmd} <- {chain(ppid)}")
        seen = now


if __name__ == "__main__":
    try:
        main()
    except Exception as e:            # jamais de fenêtre d'erreur : une trace dans le fichier
        write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} guet arrêté : {e!r}")
