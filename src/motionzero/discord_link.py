"""Liaison avec le bot Discord (dépôt iris-discord-bot, issue #19).

- Le bot est un processus à part : s'il plante, Iris continue. Iris le lance s'il ne répond pas (au plus
  une fois par minute) ; lui relance Iris si elle se fige ou s'arrête sans « bye ».
- Un fil « pont-bot » parle au bot (socket local, une ligne JSON par message) et ne touche jamais Core :
  ce qu'il reçoit va dans `inbox`, vidée par la boucle principale.
- Le secret et le port sont lus dans le config.json du bot : rien à recopier. Bot absent : liaison éteinte.
"""
import json
import logging
import os
import queue
import socket
import subprocess
import threading
import time

log = logging.getLogger("motionzero.discord_bot")

PROTOCOL_VERSION = 1
PING_S = 10.0
RETRY_S = (1, 2, 5, 10, 30)          # attente entre deux tentatives de connexion
LAUNCH_EVERY_S = 60.0                # au plus un lancement du bot par minute
DEFAULT_BOT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "iris-discord-bot")


def read_bot_config(bot_dir):
    """(port, secret) depuis le config.json du bot, ou None s'il manque ou est invalide."""
    try:
        with open(os.path.join(bot_dir, "config.json"), encoding="utf-8") as f:
            raw = json.load(f)
        secret = str(raw.get("ipc_secret", ""))
        if len(secret) < 16:
            return None
        return int(raw.get("port", 47821)), secret
    except (OSError, ValueError, TypeError, AttributeError):
        return None


class BotLink:
    def __init__(self, bot_dir=DEFAULT_BOT_DIR, launch=True, connect=socket.create_connection,
                 clock=time.monotonic):
        self.bot_dir = bot_dir
        self.launch_enabled = launch
        self.connect = connect
        self.clock = clock
        self.inbox = queue.Queue(maxsize=200)   # bot -> boucle principale
        self._out = queue.Queue(maxsize=50)     # boucle principale -> bot
        self._stop = threading.Event()
        self._sock = None
        self._req = 0
        self._last_launch = -1e9
        self.connected = False
        self.was_connected = False          # au moins une connexion réussie (pour l'île)
        self.kinds = {}                     # numéro de commande -> « send » / « move »
        self.conf = read_bot_config(bot_dir)

    @property
    def enabled(self):
        return self.conf is not None

    def start(self):
        if not self.enabled:
            log.info("bot Discord absent (%s) : liaison eteinte", self.bot_dir)
            return self
        threading.Thread(target=self._run, name="pont-bot", daemon=True).start()
        return self

    # ---- appelé depuis la boucle principale (n'attend jamais) ----
    def send(self, msg):
        """Met une commande en file ; renvoie son numéro, ou None si le bot est absent / la file pleine."""
        if not self.enabled or not self.connected:
            return None
        self._req += 1
        self.kinds[self._req] = msg.get("t")
        if len(self.kinds) > 50:
            self.kinds.pop(next(iter(self.kinds)))
        try:
            self._out.put_nowait({**msg, "req": self._req})
        except queue.Full:
            return None
        return self._req

    def bye(self):
        """Arrêt volontaire (STOP) : le bot ne doit pas relancer Iris."""
        sock = self._sock
        self._stop.set()
        if sock is not None:
            try:
                sock.sendall(b'{"t":"bye"}\n')
            except OSError:
                pass

    # ---- fil « pont-bot » ----
    def _run(self):
        tries = 0
        while not self._stop.is_set():
            try:
                self._session()
                tries = 0
            except (OSError, ValueError) as e:
                if tries == 0:
                    log.info("bot Discord injoignable (%s)", e.__class__.__name__)
                if isinstance(e, ConnectionRefusedError):
                    self._maybe_launch()
            except Exception:
                log.exception("liaison bot")
            if self.connected:             # une seule annonce par coupure, pas à chaque tentative
                self._put({"t": "link", "connected": False})
            self.connected = False
            self._stop.wait(RETRY_S[min(tries, len(RETRY_S) - 1)])
            tries += 1

    def _session(self):
        port, secret = self.conf
        sock = self.connect(("127.0.0.1", port), timeout=3)
        sock.settimeout(1.0)
        self._sock = sock
        try:
            sock.sendall(_line({"t": "hello", "token": secret, "v": PROTOCOL_VERSION}))
            buf = b""
            hello_until = self.clock() + 5
            last_ping = self.clock()
            while not self._stop.is_set():
                # envois en attente
                while True:
                    try:
                        sock.sendall(_line(self._out.get_nowait()))
                    except queue.Empty:
                        break
                now = self.clock()
                if self.connected and now - last_ping >= PING_S:
                    sock.sendall(b'{"t":"ping"}\n')
                    last_ping = now
                if not self.connected and now > hello_until:
                    raise ValueError("pas de reponse du bot")
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    raise ConnectionResetError("bot deconnecte")
                buf += chunk
                if len(buf) > 1_000_000:
                    raise ValueError("ligne trop longue")
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._on_line(line)
        finally:
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass

    def _on_line(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            log.warning("bot : ligne illisible")
            return
        if not isinstance(msg, dict):
            return
        if msg.get("t") == "hello":
            self.connected = self.was_connected = True
            log.info("bot Discord connecte")
            self._put({"t": "link", "connected": True})
            return
        if msg.get("t") == "result" and msg.get("error") in ("secret_refuse", "version_incompatible"):
            log.error("bot Discord : %s", msg["error"])
            self._stop.wait(30)           # inutile d'insister vite : configuration à corriger
            raise ValueError(msg["error"])
        self._put(msg)

    def _put(self, msg):
        try:
            self.inbox.put_nowait(msg)
        except queue.Full:                 # boucle principale en retard : on jette le plus vieux
            try:
                self.inbox.get_nowait()
                self.inbox.put_nowait(msg)
            except (queue.Empty, queue.Full):
                pass

    def _maybe_launch(self):
        if not self.launch_enabled or self.clock() - self._last_launch < LAUNCH_EVERY_S:
            return
        self._last_launch = self.clock()
        exe = os.path.join(self.bot_dir, ".venv", "Scripts", "pythonw.exe")
        if not os.path.exists(exe):
            log.warning("bot Discord : %s introuvable, pas de lancement", exe)
            return
        try:
            subprocess.Popen([exe, "-m", "iris_discord_bot"], cwd=self.bot_dir,
                             creationflags=0x08000000 | 0x00000008, close_fds=True)
            log.info("bot Discord lance")
        except OSError:
            log.exception("lancement du bot Discord")


def _line(msg):
    return json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"


ERRORS = {"salon_inconnu": "SALON INCONNU", "pas_en_vocal": "TU N'ES PAS EN VOCAL",
          "permission_manquante": "PERMISSION MANQUANTE", "message_vide": "MESSAGE VIDE",
          "commande_inconnue": "BOT A METTRE A JOUR", "pas_compris": "PAS COMPRIS",
          "vocal_impossible": "VOCAL IMPOSSIBLE"}


def result_label(msg, kind="send"):
    """Texte de l'île pour la réponse du bot à une commande (« send » ou « move »)."""
    if msg.get("ok") and kind == "join":
        return f"IRIS EN VOCAL : {msg.get('channel', '?')}".upper()[:60]
    if msg.get("ok") and kind == "leave":
        return "IRIS A QUITTE LE VOCAL"
    if msg.get("ok") and kind == "activate":
        return "BOT VOCAL PRET : DIS IRIS VIENS"
    if msg.get("ok"):
        done = "ENVOYE DANS #" if kind == "send" else "SALON "
        return f"DISCORD : {done}{msg.get('channel', '?')}".upper()[:60]
    label = ERRORS.get(msg.get("error"), f"DISCORD : ERREUR {msg.get('error', '?')}")
    sugg = msg.get("suggestions") or []
    if sugg:
        label += " (" + ", ".join(sugg[:2]) + " ?)"
    return label.upper()[:60]


def speech_for(msg):
    """Phrase lue à voix haute pour un message Discord."""
    who = msg.get("author") or "quelqu'un"
    where = "en privé" if msg.get("dm") else f"dans {msg.get('channel') or 'un salon'}"
    if msg.get("mention_me") and not msg.get("mention"):
        return f"{who} te mentionne {where} : {msg.get('content', '')}"
    return f"{who}, {where} : {msg.get('content', '')}"
