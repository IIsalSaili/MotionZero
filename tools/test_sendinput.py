"""Étape 0 : déplace le curseur aux 4 coins via SendInput (aucun clic), puis le remet en place."""
import ctypes
import json
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
# DPI : per-monitor V2, avant tout calcul de coordonnées
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    user32.SetProcessDPIAware()

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


SM_XVS, SM_YVS, SM_CXVS, SM_CYVS = 76, 77, 78, 79
vx, vy = user32.GetSystemMetrics(SM_XVS), user32.GetSystemMetrics(SM_YVS)
vw, vh = user32.GetSystemMetrics(SM_CXVS), user32.GetSystemMetrics(SM_CYVS)


def move_to(x, y):
    nx = int((x - vx) * 65535 / max(vw - 1, 1))
    ny = int((y - vy) * 65535 / max(vh - 1, 1))
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
    t0 = time.perf_counter()
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    return sent, (time.perf_counter() - t0) * 1000


def get_pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


orig = get_pos()
targets = [(vx, vy), (vx + vw - 1, vy), (vx + vw - 1, vy + vh - 1), (vx, vy + vh - 1), (vx + vw // 2, vy + vh // 2)]
results = []
for tx, ty in targets:
    sent, ms = move_to(tx, ty)
    time.sleep(0.35)
    px, py = get_pos()
    results.append({"cible": [tx, ty], "obtenu": [px, py], "ecart_px": max(abs(px - tx), abs(py - ty)),
                    "envoye": sent, "appel_ms": round(ms, 3)})
move_to(*orig)
print(json.dumps({"ecran_virtuel": [vx, vy, vw, vh], "position_initiale": orig, "tests": results},
                 ensure_ascii=False, indent=1))
