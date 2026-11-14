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
SW_SHOW = 5


def find_window(title_part="Visual Studio Code"):
    """Fenêtre VS Code visible (la plus haute dans l'ordre d'affichage), ou None. Cherchée d'abord par le
    programme (Code.exe) : un onglet Chrome ou un autre programme peut avoir « Visual Studio Code » dans son titre."""
    if title_part == "Visual Studio Code":
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd and _exe_of(hwnd) == "code.exe":
            return hwnd
        found = find_app_window("code.exe")
        if found:
            return found
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
    for _ in range(25):
        if u.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    # 2e essai (mesuré le 12/11 : Chrome réduit dans la barre des tâches, refusé 3 fois de suite) :
    # SwitchToThisWindow, comme Alt+Tab, et plus de temps pour l'animation de restauration
    u.ShowWindow(hwnd, SW_RESTORE if u.IsIconic(hwnd) else SW_SHOW)
    u.SwitchToThisWindow(hwnd, True)
    for _ in range(50):
        if u.GetForegroundWindow() == hwnd:
            log.info("premier plan obtenu au 2e essai")
            return True
        time.sleep(0.02)
    log.warning("premier plan refuse (fenetre %s)", hwnd)
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


# --- état partagé ---------------------------------------------------------------------------------
SINK_HWND = None   # fenêtre invisible de motionzero qui reçoit le raccourci Discord (voir ui.KeySink)


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
EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x6F, 0x90, 0xA3, 0xA5}


def send_discord(action):
    """Envoie le raccourci Discord d'une action (lu dans les réglages de Discord, voir discord_keys),
    dans la fenêtre invisible de motionzero : rien ne se tape ailleurs, Discord le capte partout."""
    from .discord_keys import combo
    u = ctypes.windll.user32
    keys = combo(action)
    if not keys:
        return False
    if SINK_HWND and not bring_to_front(SINK_HWND):
        log.warning("fenetre invisible pas au premier plan : raccourci Discord non envoye")
        return False
    def key(vk, up):
        flags = (1 if vk in EXTENDED_VK else 0) | (2 if up else 0)
        u.keybd_event(vk, u.MapVirtualKeyW(vk, 0), flags, 0)
    for vk in keys:
        key(vk, False)
    time.sleep(0.05)
    for vk in reversed(keys):
        key(vk, True)
    time.sleep(0.05)
    log.info("discord : %s (%s)", action, "+".join(hex(k) for k in keys))
    return True


def discord_mute_toggle():
    """« iris mute / démute » : le raccourci « couper le micro » de Discord, tel que réglé dans Discord."""
    return send_discord("TOGGLE_MUTE")


# --- « Iris, Discord » / « Iris, Chrome » : passer sur l'appli (ou la lancer) ------------------------
APPS = {
    "discord": ("discord.exe", [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe"),
                                "--processStart", "Discord.exe"]),
    "chrome": ("chrome.exe", [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]),
    "studio": ("code.exe", [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")]),
}


def vscode_in_front():
    """VS Code est-il au premier plan ? Par le programme (Code.exe), pas par le titre : le 14/11, une autre
    fenêtre contenant « Visual Studio Code » dans son titre faisait dire « VS Code pas devant » à tort."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return bool(hwnd) and _exe_of(hwnd) == "code.exe"


IRIS_EXES = ("python.exe", "pythonw.exe")


def foreground_exe():
    """Programme de la fenêtre au premier plan (« code.exe », « pythonw.exe » pour Iris…), ou ""."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return _exe_of(hwnd) if hwnd else ""


def chrome_in_front():
    """Chrome est-il la fenêtre au premier plan ? (mode CHROME : aucune touche envoyée ailleurs)"""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return bool(hwnd) and _exe_of(hwnd) == "chrome.exe"


def _exe_of(hwnd):
    """Nom du programme d'une fenêtre (ex. « chrome.exe »), en minuscules."""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if not k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        k.CloseHandle(h)


def find_app_window(exe):
    """Fenêtre principale visible d'un programme (la plus haute à l'écran), ou None."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if (u.IsWindowVisible(hwnd) and u.GetWindowTextLengthW(hwnd) > 0
                and not u.GetWindow(hwnd, 4)           # GW_OWNER : pas une fenêtre secondaire
                and _exe_of(hwnd) == exe):
            found.append(hwnd)
            return False
        return True

    u.EnumWindows(cb, 0)
    return found[0] if found else None


def _title_of(hwnd):
    u = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(u.GetWindowTextLengthW(hwnd) + 1)
    u.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def open_home():
    """« iris accueil » : la fenêtre d'aperçu de motionzero (caméra, commandes), au premier plan, à sa taille normale."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid() and _title_of(hwnd) == "motionzero":
            found.append(hwnd)
            return False
        return True

    u.EnumWindows(cb, 0)
    if not found:
        return "APERCU INTROUVABLE"
    u.ShowWindow(found[0], 9)   # SW_RESTORE : taille normale (rouvre une fenêtre réduite ou agrandie)
    if not bring_to_front(found[0]):
        return "APERCU PAS AU PREMIER PLAN"
    log.info("apercu motionzero au premier plan")
    return None


def open_app(name):
    """Met l'appli au premier plan, ou la lance si elle n'est pas ouverte. Renvoie None ou une erreur."""
    import subprocess
    if name == "accueil":
        return open_home()
    exe, cmd = APPS[name]
    hwnd = find_app_window(exe)
    if hwnd:
        if not bring_to_front(hwnd):
            return f"{name.upper()} PAS AU PREMIER PLAN"
        log.info("%s au premier plan", name)
        return None
    try:
        subprocess.Popen(cmd, close_fds=True)
    except OSError:
        log.warning("%s introuvable : %s", name, cmd[0])
        return f"{name.upper()} INTROUVABLE"
    log.info("%s lance", name)
    return None
