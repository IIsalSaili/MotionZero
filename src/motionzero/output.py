"""Envoi des entrées à Windows (SendInput) + chien de garde qui relâche tout ce qui est maintenu."""
import ctypes
import sys
from ctypes import wintypes

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSEEVENTF_WHEEL = 0x0800
BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
VK = {"right": 0x27, "left": 0x25, "up": 0x26, "down": 0x28,
      "pagedown": 0x22, "pageup": 0x21, "space": 0x20,
      "enter": 0x0D, "escape": 0x1B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
      "c": 0x43, "v": 0x56, "a": 0x41, "esc": 0x1B, "f9": 0x78, "backspace": 0x08}
EXTENDED = {"right", "left", "up", "down", "pagedown", "pageup"}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def set_dpi_aware():
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor V2
    except Exception:
        user32.SetProcessDPIAware()


def primary_screen():
    user32 = ctypes.windll.user32
    return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


class SendInputBackend:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.vx, self.vy = self.user32.GetSystemMetrics(76), self.user32.GetSystemMetrics(77)
        self.vw, self.vh = self.user32.GetSystemMetrics(78), self.user32.GetSystemMetrics(79)

    def _send(self, inp):
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def move(self, x, y):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(int((x - self.vx) * 65535 / max(self.vw - 1, 1)),
                            int((y - self.vy) * 65535 / max(self.vh - 1, 1)), 0,
                            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
        self._send(inp)

    def button(self, which, down):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(0, 0, 0, BUTTON_FLAGS[which][0 if down else 1], 0, 0)
        self._send(inp)

    def wheel(self, delta):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(0, 0, int(delta) & 0xFFFFFFFF, MOUSEEVENTF_WHEEL, 0, 0)
        self._send(inp)

    def key(self, name, down):
        vk = VK[name]
        flags = (KEYEVENTF_EXTENDEDKEY if name in EXTENDED else 0) | (0 if down else KEYEVENTF_KEYUP)
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(vk, self.user32.MapVirtualKeyW(vk, 0), flags, 0, 0)
        self._send(inp)


class FakeBackend:
    """N'envoie rien : enregistre les événements (tests et mode simulation)."""

    def __init__(self):
        self.events = []

    def move(self, x, y):
        self.events.append(("move", x, y))

    def button(self, which, down):
        self.events.append(("button", which, down))

    def wheel(self, delta):
        self.events.append(("wheel", delta))

    def key(self, name, down):
        self.events.append(("key", name, down))


class Controller:
    """Exécute les actions. Tout ce qui est maintenu est suivi et relâché automatiquement."""

    def __init__(self, backend, cfg):
        self.b = backend
        self.cfg = cfg
        self.held = {}  # ("mouse"|"key", nom) -> instant d'appui

    def _press(self, kind, name, t):
        if (kind, name) in self.held:
            return
        (self.b.button if kind == "mouse" else self.b.key)(name, True)
        self.held[(kind, name)] = t

    def _release(self, kind, name):
        if self.held.pop((kind, name), None) is not None:
            (self.b.button if kind == "mouse" else self.b.key)(name, False)

    def release_all(self):
        for kind, name in list(self.held):
            self._release(kind, name)

    def execute(self, acts, t):
        for a in acts:
            kind = a[0]
            if kind == "move":
                self.b.move(a[1], a[2])
            elif kind == "click":
                self.b.button(a[1], True)
                self.b.button(a[1], False)
            elif kind == "key":
                self.b.key(a[1], True)
                self.b.key(a[1], False)
            elif kind == "scroll":
                self.b.wheel(a[1])
            elif kind == "hotkey":  # ex. ["ctrl", "c"] : appuis dans l'ordre, relâchés à l'envers
                for k in a[1]:
                    self.b.key(k, True)
                for k in reversed(a[1]):
                    self.b.key(k, False)
            elif kind == "press":
                self._press(a[1], a[2], t)
            elif kind == "release":
                self._release(a[1], a[2])
            elif kind == "release_all":
                self.release_all()
        for (kind, name), t0 in list(self.held.items()):
            if t - t0 > self.cfg.max_hold_s:
                self._release(kind, name)
