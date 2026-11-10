"""« Iris, Claude » : met VS Code au premier plan puis allume / éteint le micro du panneau Claude.

Le micro est déclenché par la commande cachée de l'extension « claude-vscode.toggleDictation », reliée au
raccourci DICTATION_KEYS dans %APPDATA%\\Code\\User\\keybindings.json. VS Code est mis au premier plan AVANT
d'envoyer la touche : elle ne peut donc plus partir dans une autre fenêtre (Chrome…).
"""
import ctypes
import logging
import os
import time
from ctypes import wintypes

log = logging.getLogger("motionzero.vscode")
DICTATION_KEYS = ["ctrl", "alt", "shift", "f9"]
SW_RESTORE = 9


def find_window(title_part="Visual Studio Code"):
    """Fenêtre VS Code visible (la plus haute dans l'ordre d'affichage), ou None."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value:
                found.append(hwnd)
                return False
        return True

    u.EnumWindows(cb, 0)
    return found[0] if found else None


def bring_to_front(hwnd):
    """Windows refuse souvent SetForegroundWindow à un programme en arrière-plan. Contournement classique :
    un appui Alt (débloque le verrou du premier plan) puis rattachement temporaire au fil de la fenêtre active."""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, SW_RESTORE)
    u.keybd_event(0x12, 0, 0, 0)       # Alt enfoncé
    u.keybd_event(0x12, 0, 2, 0)       # Alt relâché
    fg = u.GetForegroundWindow()
    a = u.GetWindowThreadProcessId(fg, None)
    b = k.GetCurrentThreadId()
    u.AttachThreadInput(b, a, True)
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        u.AttachThreadInput(b, a, False)
    for _ in range(20):
        if u.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


def focus_and_send(send_hotkey, key_groups):
    """Met VS Code au premier plan puis envoie chaque groupe de touches (ex. [["ctrl", "a"], ["backspace"]]).
    Renvoie None si tout va bien, sinon un texte d'erreur pour l'affichage."""
    u = ctypes.windll.user32
    hwnd = find_window()
    if hwnd is None:
        log.warning("VS Code introuvable")
        return "VS CODE INTROUVABLE"
    if u.GetForegroundWindow() != hwnd:
        remember_previous(hwnd)
        if not bring_to_front(hwnd):
            log.warning("VS Code n'a pas pu passer au premier plan")
            return "VS CODE PAS AU PREMIER PLAN"
        time.sleep(0.15)  # laisser VS Code prendre le focus clavier
    for keys in key_groups:
        send_hotkey(keys)
        time.sleep(0.05)
    log.info("VS Code : %s", " puis ".join("+".join(k) for k in key_groups))
    return None


def toggle_claude_dictation(send_hotkey):
    """Allume / éteint le micro du panneau Claude."""
    return focus_and_send(send_hotkey, [DICTATION_KEYS])


# --- « Iris, retour » : revenir à la fenêtre d'avant « Iris, Claude » -----------------------------
_previous = None   # fenêtre au premier plan juste avant qu'« Iris, Claude » passe sur VS Code
SINK_HWND = None   # fenêtre invisible de motionzero qui reçoit le raccourci Discord (voir ui.KeySink)


def _title(hwnd):
    u = ctypes.windll.user32
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value[:80]


def remember_previous(vscode_hwnd):
    """Retient la fenêtre active (YouTube, autre appli…) avant de passer sur VS Code."""
    global _previous
    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
    if fg and fg != vscode_hwnd and pid.value != os.getpid():   # jamais nos propres fenêtres
        _previous = fg
        log.info("fenetre retenue pour « retour » : %s", _title(fg))


def go_back():
    """Remet au premier plan la fenêtre retenue. Renvoie None, ou un texte d'erreur."""
    u = ctypes.windll.user32
    if not _previous or not u.IsWindow(_previous):
        return "RIEN A QUOI REVENIR"
    if not bring_to_front(_previous):
        return "RETOUR IMPOSSIBLE"
    log.info("retour a : %s", _title(_previous))
    return None


# --- « Iris, tab » : comme Alt+Tab -------------------------------------------------------------------
def alt_tab():
    u = ctypes.windll.user32
    u.keybd_event(0x12, 0x38, 0, 0)        # Alt enfoncé
    u.keybd_event(0x09, 0x0F, 0, 0)        # Tab
    u.keybd_event(0x09, 0x0F, 2, 0)
    time.sleep(0.05)
    u.keybd_event(0x12, 0x38, 2, 0)        # Alt relâché : Windows passe à la fenêtre suivante
    log.info("alt+tab")


# --- Discord : raccourci de micro coupé (Suppr + « + » du pavé numérique) -----------------------------
def discord_mute_toggle():
    """Envoie Suppr du pavé numérique + « + » du pavé numérique, comme les vraies touches, dans la
    fenêtre invisible de motionzero (rien ne se tape ailleurs). Discord, lui, les capte partout.
    Pavé numérique activé : la touche Suppr/point envoie « point décimal » ; désactivé : Suppr."""
    u = ctypes.windll.user32
    if SINK_HWND and not bring_to_front(SINK_HWND):
        log.warning("fenetre invisible pas au premier plan : raccourci Discord non envoye")
        return False
    del_vk = 0x6E if u.GetKeyState(0x90) & 1 else 0x2E   # VK_DECIMAL ou VK_DELETE, même touche (code 0x53)
    u.keybd_event(del_vk, 0x53, 0, 0)
    u.keybd_event(0x6B, 0x4E, 0, 0)        # VK_ADD, « + » du pavé numérique
    time.sleep(0.05)
    u.keybd_event(0x6B, 0x4E, 2, 0)
    u.keybd_event(del_vk, 0x53, 2, 0)
    time.sleep(0.05)
    log.info("discord : micro bascule")
    return True
