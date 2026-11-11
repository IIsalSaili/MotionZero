"""Application : caméra -> points de la main -> machine à états -> souris/clavier.

  python -m motionzero               normal
  python -m motionzero --simulation  n'envoie rien à Windows (affiche seulement)

Pour arrêter : uniquement le petit bouton STOP en bas à droite (clic, ou main tenue dessus).
L'interface est en Qt (fil principal) ; caméra, MediaPipe et Core tournent dans un fil à part.
"""
import argparse
import ctypes
import logging
import os
import queue
import threading
import time
from collections import deque

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from .camera import OK, Camera
from .config import load_config
from .core import Core, Mode
from .hand import HandTracker
from .overlay import render
from .output import Controller, FakeBackend, SendInputBackend, primary_screen, set_dpi_aware
from .sounds import Sounds
from .ui import Bridge, EyeButton, GlassOverlay, KeySink, PreviewWindow, QApplication, StopButton, set_capture_visible

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIN = "motionzero"
DETECT_MAX_FPS = 20          # plafond de détection (moins de charge)
IDLE_DETECT_FPS = 5          # sans main depuis IDLE_AFTER_S (ou appli en pause) : détection ralentie
IDLE_AFTER_S = 2.0
STALE_S = 0.5                # sans image depuis 0,5 s : caméra considérée perdue


def lower_priority():
    """Priorité « inférieure à la normale » : un jeu ou une appli lourde passe toujours avant motionzero."""
    try:
        BELOW_NORMAL = 0x4000
        k32 = ctypes.windll.kernel32
        # handle typé : en entier simple, le « -1 » du processus courant était tronqué (appel sans effet)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL):
            raise OSError(ctypes.GetLastError())
    except Exception:
        logging.getLogger("motionzero").warning("priorite du processus non changee")


def detect_period(disabled, last_hand_t, t):
    """Intervalle entre deux détections : pleine vitesse avec une main, ralenti sinon."""
    if disabled or t - last_hand_t >= IDLE_AFTER_S:
        return 1.0 / IDLE_DETECT_FPS
    return 1.0 / DETECT_MAX_FPS


def main(argv=None):
    ap = argparse.ArgumentParser(prog="motionzero")
    ap.add_argument("--simulation", action="store_true", help="n'envoie rien a Windows")
    ap.add_argument("--voice", action="store_true", help="active les commandes vocales (micro)")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--duration", type=float, default=0, help="arret automatique apres N secondes (tests)")
    ap.add_argument("--screenshot", default="", help="enregistre la derniere image de l'appli (tests)")
    args = ap.parse_args(argv)

    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    # journal tournant (3 x 2 Mo) : l'appli reste ouverte en permanence, le fichier ne grossit plus sans fin
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(os.path.join(ROOT, "logs", "motionzero.log"), maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    logging.basicConfig(handlers=[handler], level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log = logging.getLogger("motionzero")
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)   # une ligne par transcription : inutile
    lower_priority()
    # erreurs dans l'interface (Qt) ou dans un fil : notées dans le journal, jamais silencieuses
    # (lancé par le raccourci du bureau, sans console, elles étaient perdues)
    import sys
    sys.excepthook = lambda *e: log.error("erreur non rattrapee", exc_info=e)
    threading.excepthook = lambda a: log.error("erreur dans le fil %s", a.thread.name if a.thread else "?",
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    set_dpi_aware()
    cfg = load_config(args.config)
    core = Core(cfg, primary_screen())
    try:                                       # repères des poses de l'utilisateur (index pointé = clic)
        from .poses import load_centroids
        core.pose_cents = load_centroids(os.path.join(ROOT, "calibration", "poses.json"))
    except (OSError, ValueError, KeyError):
        log.warning("calibration des poses absente : pas de clic par l'index")
    tracker = HandTracker()
    backend = FakeBackend() if args.simulation else SendInputBackend()
    ctl = Controller(backend, cfg)
    sounds = Sounds(os.path.join(ROOT, "assets", "sounds"), cfg.sounds)
    # les DEUX mains sont détectées (demande de l'utilisateur) ; CPU mesuré ~7 % : marge suffisante
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "hand_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_hands=2))
    cam = Camera(cfg.camera_index, cfg.width, cfg.height).start()
    listener = None
    if args.voice:
        from .voice import VoiceListener, default_model_dir
        listener = VoiceListener(default_model_dir(ROOT)).start()
    from .ask import Asker
    asker = Asker()                            # « iris question » -> Whisper -> Claude Haiku
    if listener is not None:                   # sans la voix, Whisper ne sert à rien : pas chargé
        asker.preload()
    from .typer import Typer
    typer = Typer(asker)                       # « iris type » -> Whisper -> texte écrit au curseur
    launcher = None
    app_messages = queue.Queue()

    def app_message(msg):
        # appelé depuis un fil d'arrière-plan : le message est remis à la boucle principale.
        # (Modifier core.last_gesture ici changeait l'historique pendant son affichage : plantage.)
        app_messages.put(msg)
    if listener is not None:                   # « iris ouvre » + nom de l'appli (Whisper)
        from .apps import Launcher
        launcher = Launcher(asker, app_message)
    # bot Discord (processus à part, issue #19) : lecture des messages, « iris message », « iris salon »
    from .discord_link import BotLink
    from .speech import Speaker
    bot = BotLink(launch=not args.simulation and not args.duration).start()
    speaker = Speaker() if bot.enabled else None
    # micro / sourdine Discord : simple mémoire tant que l'appli tourne (demande de l'utilisateur).
    # Au lancement : micro allumé, pas de sourdine. Rien n'est enregistré ni lu dans Discord.
    discord_voice = {"mute": False, "deaf": False}

    # VS Code (micro de Claude, Entrée) : toujours envoyé pour de vrai, même en simulation,
    # sinon la dictée ne peut pas être essayée. Seules ces touches-là, et seulement vers VS Code.
    vscode_ctl = Controller(SendInputBackend(), cfg)
    log.info("demarrage (simulation=%s) camera=%s", args.simulation, cam.info)

    # Qt : l'interface tourne dans le fil principal, caméra + MediaPipe + Core dans un fil à part.
    qt = QApplication.instance() or QApplication([])
    view_win = PreviewWindow()
    stop = threading.Event()
    bridge = Bridge()
    bridge.frame.connect(view_win.set_frame)   # file d'attente Qt : passe d'un fil à l'autre
    # panneau « Consommation » de la page d'accueil : mesuré seulement quand la page est visible
    live = {"detect_hz": DETECT_MAX_FPS}       # écrit par la boucle, lu par le fil de mesure

    def model_info():
        return {"whisper": asker._whisper is not None, "detect_hz": live["detect_hz"],
                "voice_on": listener is not None,
                "free_awake": listener is not None and time.perf_counter() < getattr(listener, "_free_until", 0)}

    bridge.stats.connect(view_win.conso.set_stats)
    from .stats import run_sampler
    threading.Thread(target=run_sampler, args=(lambda: view_win.visible_flag, bridge.stats.emit, model_info, stop),
                     name="mesures", daemon=True).start()
    glass = GlassOverlay("ui")                 # île, logo, pastille Discord : visibles dans les partages
    cursor_glass = GlassOverlay("cursor")      # curseur de la main + loupe : jamais dans les captures
    bridge.state.connect(glass.set_state)
    bridge.state.connect(cursor_glass.set_state)
    stop_btn = StopButton()                    # arrêt d'urgence, en bas à droite
    eye_btn = EyeButton(stop_btn)              # œil : montrer / masquer l'overlay dans les partages

    def show_in_captures(visible):
        for w in (glass, stop_btn):
            set_capture_visible(w, visible)
        log.info("overlay %s dans les partages d'ecran", "visible" if visible else "masque")

    eye_btn.toggled.connect(show_in_captures)
    bridge.done.connect(qt.quit)

    def emergency(source):
        """STOP : tout relâcher tout de suite (sans attendre le moteur), puis quitter."""
        if not stop.is_set():
            log.info("STOP (%s)", source)
        stop.set()
        ctl.release_all()
        bot.bye()                              # arrêt voulu : le bot ne relance pas Iris
        qt.quit()

    glass.closed.connect(lambda: emergency("verre ferme"))
    cursor_glass.closed.connect(lambda: emergency("verre ferme"))
    stop_btn.closed.connect(lambda: emergency("bouton ferme"))
    stop_btn.triggered.connect(lambda: emergency("bouton STOP"))
    qt.aboutToQuit.connect(stop.set)

    def show(img):
        bridge.frame.emit(img)

    def run_engine():
        try:
            _loop()
        except Exception:
            log.exception("erreur dans la boucle principale")
        finally:
            bridge.done.emit()

    def _loop():
        t0 = time.perf_counter()
        seq, last_ts, fps, frames, fps_t = 0, -1, 0.0, 0, t0
        last_detect, last_frame_t = 0.0, t0
        last_view = np.zeros((cfg.height, cfg.width, 3), np.uint8)
        pts = None
        last_level_log = 0.0
        last_hand_t = t0
        errors = deque(maxlen=20)
        try:
            while not stop.is_set():
                try:
                    t = time.perf_counter()
                    frame, new_seq = cam.read(seq)
                    disabled = core.mode == Mode.DISABLED
                    live["detect_hz"] = 0 if disabled else 1.0 / detect_period(False, last_hand_t, t)
                    if frame is not None and t - last_detect >= detect_period(disabled, last_hand_t, t):
                        seq = new_seq
                        last_detect = last_frame_t = t
                        view = cv2.flip(frame, 1)
                        all_hands, world_hands = [], []
                        if not disabled:   # en pause, la main ne sert à rien : pas de MediaPipe
                            ts = max(int((t - t0) * 1000), last_ts + 1)
                            last_ts = ts
                            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
                            res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                            all_hands = [[(p.x, p.y) for p in h] for h in res.hand_landmarks]
                            world_hands = res.hand_world_landmarks
                        pts = tracker.update(all_hands, t)  # les deux mains suivies ; celle qui bouge agit
                        if all_hands:
                            last_hand_t = t
                        world = None                        # la même main en 3D (index pointé = clic)
                        for j, h in enumerate(all_hands):
                            if h is pts and j < len(world_hands):
                                world = [(p.x, p.y, p.z) for p in world_hands[j]]
                        acts = core.step(pts, t, world)
                        frames += 1
                        if t - fps_t >= 1.0:
                            fps, frames, fps_t = frames / (t - fps_t), 0, t
                    elif t - last_frame_t > STALE_S + detect_period(disabled, last_hand_t, t):
                        # caméra muette : on traite comme « main absente » (relâche tout, puis repos)
                        view, pts = last_view.copy() // 3, None
                        acts = core.step(None, t)
                    else:
                        view, acts = None, []
                        if frame is not None:
                            # image dispo mais plafond atteint : on dort jusqu'à la prochaine détection
                            # (au plus 20 ms, pour que la voix reste réactive)
                            wait = last_detect + detect_period(disabled, last_hand_t, t) - t
                            time.sleep(min(max(wait, 0.005), 0.02))

                    if listener is not None:
                        acts = acts + core.dictation_tick(t, listener.last_speech_t)
                        acts = acts + core.ask_tick(t, listener.last_speech_t)
                        acts = acts + core.type_tick(t, listener.last_speech_t)
                        acts = acts + core.open_tick(t, listener.last_speech_t)
                    while not app_messages.empty():
                        core.last_gesture = (app_messages.get_nowait(), t)
                    bot_events(bot, core, speaker, discord_voice, t)
                    if listener is not None:
                        if t - listener.iris_heard_t < 0.5:
                            core.freeze_for_voice(t)   # « iris » en cours de prononciation : curseur figé
                        for ev in listener.poll():
                            acts = acts + core.voice(ev.word, ev.t_end, t_start=ev.t_start)
                            accepted = core.last_word and core.last_word[2]
                            log.info("voix %s (%.2f) %s", ev.word, ev.conf, "acceptee" if accepted else "ignoree (ecoute fermee)")
                            if ev.word == "iris" and accepted:
                                sounds.play("ECOUTE")
                    # le bouton STOP ne s'active QUE par un vrai clic (souris, ou clic de motionzero en mode souris) :
                    # le survol par la main l'arrêtait sans le vouloir (demande de l'utilisateur, 11/11)
                    if listener is not None and core.dictating and t - last_level_log >= 1.0:
                        last_level_log = t
                        log.info("dictee : micro rms %.0f (bruit de fond %.0f), parole il y a %.1f s",
                                 listener.last_rms, listener.ambient, t - listener.last_speech_t)
                    if listener is not None:
                        acts = question_actions(acts, listener, asker)
                        acts = type_actions(acts, listener, typer, sounds)
                        acts = open_actions(acts, listener, launcher, asker, bot, app_message)
                    acts = discord_actions(acts, speaker)
                    acts = vscode_actions(acts, core, vscode_ctl, sounds, t, discord_voice)
                    ctl.execute(acts, t)
                    for a in acts:
                        if a[0] == "mode":
                            sounds.play(a[1])
                            log.info("mode %s", a[1])
                        elif a[0] == "scroll":
                            log.info("scroll %s", a[1])
                        elif a[0] == "hotkey":
                            log.info("touches %s", "+".join(a[1]))
                        elif a[0] in ("key", "click"):
                            sounds.play("CLIC")
                            log.info("%s %s (%s)", a[0], a[1], core.last_gesture[0] if core.last_gesture else "")

                    if view is not None:
                        if pts is not None or frame is not None:
                            last_view = view.copy()
                        status = cam.status if t - last_frame_t <= STALE_S else (cam.status if cam.status != OK else "perdue")
                        # fenêtre d'aperçu réduite : on ne dessine plus l'image (20 fois par seconde pour rien)
                        if view_win.visible_flag or args.screenshot:
                            shown = render(view, core, tracker.tracks if pts is not None else [], fps,
                                           args.simulation, status, tracker.active_id, voice_on=listener is not None)
                            show(shown)
                        prog = core.progress()
                        # île : la dernière chose comprise (ou refusée), la plus récente des deux
                        toast = core.last_gesture
                        rej = listener.last_rejected if listener is not None else None
                        if rej and (not toast or rej[1] > toast[1]):
                            toast = rej
                        bridge.state.emit({
                            "show_cursor": core.mode == Mode.MOUSE,
                            "cursor": core.cursor,
                            "progress": prog[1] if prog else 0.0,
                            "lost": pts is None,
                            "arming": core.mode == Mode.MOUSE and not core.armed,
                            "mode": core.mode,
                            "dictating": core.dictating,
                            "typing": core.typing or core.opening,
                            "confirming": core.confirming(t),
                            "listening": core.listening(t),
                            "toast": toast[0] if toast else None,
                            # main verte 0,5 s : une commande vocale vient d'être comprise (pas « iris » seul)
                            "ok_flash": bool(core.last_word and core.last_word[2] and core.last_word[0] != "iris"
                                             and t - core.last_word[1] < 0.5),
                            "toast_age": t - toast[1] if toast else 1e9,
                            "qa": asker.snapshot() if listener is not None else None,
                            "discord": (discord_voice["mute"], discord_voice["deaf"]),
                        })
                    else:
                        time.sleep(0.002)  # rien de neuf : ne pas monopoliser le processeur
                    if args.duration and t - t0 >= args.duration:
                        if args.screenshot and "shown" in locals():
                            cv2.imwrite(args.screenshot, shown)
                        break
                except Exception:
                    # une erreur dans un tour de boucle ne doit jamais arrêter motionzero : on la note,
                    # on relâche tout ce qui est tenu, et on continue (l'utilisateur en dépend)
                    errors.append(time.perf_counter())
                    log.exception("erreur dans la boucle principale (on continue)")
                    ctl.release_all()
                    if len(errors) >= 20 and errors[-1] - errors[-20] < 10.0:
                        raise   # erreur en boucle : inutile d'insister
                    time.sleep(0.05)
        finally:
            ctl.release_all()
            if listener is not None:
                listener.stop()
            cam.stop()
            landmarker.close()
            log.info("arret (images rejetees=%d, reconnexions=%d)", cam.rejected, cam.reconnections)

    worker = threading.Thread(target=run_engine, name="moteur", daemon=True)
    worker.start()
    view_win.show()
    glass.show()
    cursor_glass.show()
    stop_btn.show()
    eye_btn.show()
    sink = KeySink()
    sink.show()
    from . import vscode
    vscode.SINK_HWND = int(sink.winId())
    qt.exec()
    stop.set()
    bot.bye()
    worker.join(timeout=3)
    if worker.is_alive():      # moteur bloqué : tout est déjà relâché, on quitte quand même
        ctl.release_all()
        log.warning("moteur bloque a l'arret : sortie forcee")
    # sortie franche : un fil resté ouvert (écoute du micro) gardait le processus en vie,
    # ce qui laissait se lancer plusieurs motionzero à la fois
    logging.shutdown()
    os._exit(0)


def question_actions(acts, listener, asker):
    """« iris question » : enregistre, puis transcription + Claude dans un fil à part ; renvoie le reste."""
    rest = []
    for a in acts:
        if a[0] == "ask_start":
            listener.start_capture()
            asker.listening()
        elif a[0] == "ask_stop":
            asker.submit(listener.stop_capture())
        elif a[0] == "ask_cancel":
            listener.stop_capture()
            asker.cancel()
        elif a[0] == "ask_close":
            asker.close()
        else:
            rest.append(a)
    return rest


def open_actions(acts, listener, launcher, asker=None, bot=None, on_message=None):
    """« iris ouvre / message / salon » : ce qui suit est enregistré, transcrit, puis traité."""
    rest = []
    for a in acts:
        if a[0] == "open_start":
            listener.start_capture()
        elif a[0] in ("message_stop", "salon_stop"):
            audio = listener.stop_capture()
            threading.Thread(target=discord_spoken, args=(a[0], audio, asker, bot, on_message),
                             name="discord", daemon=True).start()
        elif a[0] == "open_stop":
            launcher.open_spoken(listener.stop_capture())
        elif a[0] == "close_stop":
            launcher.close_spoken(listener.stop_capture())
        elif a[0] == "open_cancel":
            listener.stop_capture()
        else:
            rest.append(a)
    return rest


def discord_spoken(kind, audio, asker, bot, on_message):
    """Fil « discord » : transcrit ce qui a été dit puis le confie au bot (jamais Core ici)."""
    try:
        text = asker._transcribe(audio, 16000).strip(" .")
    except Exception:
        logging.getLogger("motionzero").exception("transcription discord")
        text = ""
    if not text:
        on_message("RIEN ENTENDU")
        return
    if bot is None or not bot.connected:
        on_message("BOT DISCORD ABSENT")
        return
    msg = {"t": "send", "text": text} if kind == "message_stop" else {"t": "move", "channel": text}
    if bot.send(msg) is None:
        on_message("BOT DISCORD OCCUPE")


def bot_events(bot, core, speaker, discord_voice, t):
    """Ce que le bot a envoyé (fil « pont-bot ») : traité ici, dans la boucle principale."""
    from .discord_link import result_label, speech_for
    while True:
        try:
            msg = bot.inbox.get_nowait()
        except queue.Empty:
            return
        kind = msg.get("t")
        if kind == "message":
            core.last_gesture = (f"{msg.get('author', '?')} : {msg.get('content', '')}"[:60], t)
            if speaker is not None:
                speaker.say(speech_for(msg))
        elif kind == "voice_state":
            # état réel vu par Discord (#6) : remplace la simple mémoire des raccourcis.
            # Hors vocal, Discord ne dit rien du micro (None) : la mémoire reste telle quelle.
            if msg.get("channel") is not None and msg.get("self_mute") is not None:
                discord_voice["mute"] = bool(msg["self_mute"])
                discord_voice["deaf"] = bool(msg.get("self_deaf"))
        elif kind == "result":
            core.last_gesture = (result_label(msg, bot.kinds.pop(msg.get("req"), "send")), t)
        elif kind == "link" and not msg.get("connected") and bot.was_connected:
            core.last_gesture = ("BOT DISCORD DECONNECTE", t)


def discord_actions(acts, speaker):
    """« iris silence » / « iris lis » : lecture à voix haute des messages Discord."""
    rest = []
    for a in acts:
        if a[0] == "discord_hush":
            if speaker is not None:
                speaker.enabled = False
                speaker.hush()
        elif a[0] == "discord_read":
            if speaker is not None:
                speaker.enabled = True
        else:
            rest.append(a)
    return rest


def type_actions(acts, listener, typer, sounds):
    """« iris type » : enregistre, puis transcription et écriture au curseur dans un fil à part."""
    rest = []
    for a in acts:
        if a[0] == "type_start":
            listener.start_capture()
            sounds.play("PARLE")
        elif a[0] == "type_stop":
            typer.submit(listener.stop_capture())
            sounds.play("COUPE")
        elif a[0] == "type_cancel":
            listener.stop_capture()
        elif a[0] == "type_send":
            typer.send()
        elif a[0] == "type_erase":
            typer.erase()
        else:
            rest.append(a)
    return rest


def vscode_actions(acts, core, ctl, sounds, t, discord=None):
    """Exécute les actions VS Code (« vscode_dictation », « vscode_keys ») ; renvoie les autres."""
    from .vscode import alt_tab, discord_mute_toggle, find_window, focus_and_send, open_app, toggle_claude_dictation

    def send(keys):
        ctl.execute([("hotkey", keys)], time.perf_counter())

    rest = []
    for a in acts:
        if a[0] == "annule":
            code = find_window()
            if code and ctypes.windll.user32.GetForegroundWindow() == code:
                err = focus_and_send(send, [["ctrl", "a"], ["backspace"]])   # vide le message de Claude
            else:
                rest.append(("hotkey", ["escape"]))                         # ailleurs : touche Échap
                continue
        elif a[0] == "alt_tab":
            alt_tab()
            err = None
        elif a[0] == "open_app":
            err = open_app(a[1])
        elif a[0] in ("discord_mute", "discord_unmute"):
            # mémoire de motionzero : « mute » déjà coupé ou « démute » déjà allumé ne font rien
            # (le raccourci de Discord inverse l'état : sinon un « mute » répété rallumerait)
            want = a[0] == "discord_mute"
            discord = discord if discord is not None else {"mute": not want, "deaf": False}
            err = None
            if discord["mute"] != want:
                if discord_mute_toggle():
                    discord["mute"] = want
            else:
                core.last_gesture = ("DISCORD : DEJA " + ("COUPE" if want else "ALLUME"), t)
        elif a[0] == "discord_deafen":
            from .vscode import send_discord
            err = None if send_discord("TOGGLE_DEAFEN") else "SOURDINE : RACCOURCI DISCORD INTROUVABLE"
            if not err and discord is not None:
                discord["deaf"] = not discord["deaf"]
        elif a[0] == "vscode_dictation":
            err = toggle_claude_dictation(send)   # Discord n'est pas touché : l'utilisateur coupe lui-même
            if not err and core.dictating:
                time.sleep(0.4)          # le micro de VS Code met un instant à démarrer
                sounds.play("PARLE")     # signal : tu peux parler
            elif not err:
                sounds.play("COUPE")     # micro coupé : dis « envoie » ou « annule »
        elif a[0] == "vscode_keys":
            err = focus_and_send(send, a[1])
        else:
            rest.append(a)
            continue
        if err:  # VS Code introuvable : on le dit, et on n'attend pas une dictée qui n'a pas démarré
            core.dictating = False
            core.confirm_until = -1e9
            core.last_gesture = (err, t)
    return rest


if __name__ == "__main__":
    main()
