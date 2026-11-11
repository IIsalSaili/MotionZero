"""« Iris, type » : la dictée est transcrite sur le PC (Whisper, le même modèle que « iris question »)
puis écrite caractère par caractère là où se trouve le curseur, dans n'importe quelle application.

Ensuite « envoie » (touche Entrée) ou « annule » (efface le texte écrit). Tout passe par un seul fil
de travail, dans l'ordre : « envoie » dit pendant la transcription attend que le texte soit écrit.
"""
import ctypes
import logging
import queue
import threading

from .output import INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK

log = logging.getLogger("motionzero.typer")
KEYEVENTF_UNICODE = 0x0004


def _send_inputs(inputs):
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key(vk, up):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return inp


def type_text(text):
    """Écrit le texte tel quel (accents compris) dans la fenêtre active."""
    inputs = []
    for unit in _utf16_units(text):
        for up in (False, True):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
            inputs.append(inp)
    _send_inputs(inputs)


def _utf16_units(text):
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]


def press(name, times=1):
    vk = VK[name]
    _send_inputs([_key(vk, up) for _ in range(times) for up in (False, True)])


class Typer:
    """Un fil de travail : transcription + écriture, puis envoie / annule, toujours dans l'ordre."""

    def __init__(self, asker):
        self.asker = asker          # pour sa transcription Whisper (modèle déjà chargé)
        self.jobs = queue.Queue()
        self.last_len = 0           # caractères écrits par la dernière dictée (pour « annule »)
        threading.Thread(target=self._run, name="type", daemon=True).start()

    def submit(self, audio):
        self.jobs.put(("type", audio))

    def send(self):
        self.jobs.put(("send", None))

    def erase(self):
        self.jobs.put(("erase", None))

    def _run(self):
        while True:
            kind, audio = self.jobs.get()
            try:
                if kind == "type":
                    text = self.asker._transcribe(audio, 16000)
                    log.info("dictee : %s", text)
                    type_text(text)
                    self.last_len = len(_utf16_units(text))
                elif kind == "send":
                    press("enter")
                elif kind == "erase":
                    press("backspace", self.last_len)
                    self.last_len = 0
            except Exception:
                log.exception("dictee iris type echouee")
