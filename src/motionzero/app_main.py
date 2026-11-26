"""Application : caméra -> points de la main -> machine à états -> souris/clavier : constantes et fonctions (1/1, découpé de app.py, #52)."""
import argparse
import datetime
import logging
import os
import queue
import threading
import time
from types import SimpleNamespace

from mediapipe.tasks.python import BaseOptions, vision

from .camera import Camera
from .config import load_config
from .core import Core
from .hand import HandTracker
from .output import Controller, FakeBackend, SendInputBackend, primary_screen, set_dpi_aware
from .sounds import Sounds
from .quota import Quota, read_shown
from .ui import (Bridge, EyeButton, RepairButton, GlassOverlay, KeySink, PreviewWindow, QApplication, StopButton, set_capture_visible)

from .app_outils import (CONFIRM_WORDS, CONV_FILE, ERROR_NOTICE, POINTER_FILE, QUIET_FILE, QUOTA_FILE, VOLUME_FILE, VOLUME_STEPS, cam_down, cand_panel, detect_period, drain, last_tab, lower_priority, next_quiet, next_volume, note_error, pick_toast, plan_card, read_conversation, read_pointer, read_quiet, read_volume, reminder_shown, top_shown, watch_engine, write_pointer)  # noqa: F401
from .app_actions import (bot_absent, bot_events, discord_actions, discord_command, discord_spoken, open_actions, question_actions, type_actions, vscode_actions)  # noqa: F401






_log = logging.getLogger("motionzero")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIN = "motionzero"
DETECT_MAX_FPS = 20          # plafond de détection (moins de charge)
IDLE_DETECT_FPS = 5          # sans main depuis IDLE_AFTER_S (ou appli en pause) : détection ralentie
IDLE_AFTER_S = 2.0
STALE_S = 0.5                # sans image depuis 0,5 s : caméra considérée perdue


HOME_PERIOD_S = 0.25      # page d'accueil : 4 mises à jour par seconde suffisent


def main(argv=None):
    from .app import Engine   # ici : app importe ce module (#52), pas d'import circulaire
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
    def _hook(*e):
        log.error("erreur non rattrapee", exc_info=e)
        note_error("affichage")

    def _thread_hook(a):
        name = a.thread.name if a.thread else "?"
        log.error("erreur dans le fil %s", name, exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
        note_error(name)
    sys.excepthook = _hook
    threading.excepthook = _thread_hook

    set_dpi_aware()
    cfg = load_config(args.config)
    cfg.pointer = read_pointer(POINTER_FILE, cfg.pointer)    # main ou tête : le dernier choix est gardé
    core = Core(cfg, primary_screen())
    core.quota_shown = read_shown(QUOTA_FILE)                # « iris quota » : le dernier choix est gardé
    try:                                       # repères des poses de l'utilisateur (index pointé = clic)
        from .poses import load_centroids
        core.pose_cents = load_centroids(os.path.join(ROOT, "calibration", "poses.json"))
    except (OSError, ValueError, KeyError):
        log.warning("calibration des poses absente : pas de clic par l'index")
    tracker = HandTracker()
    backend = FakeBackend() if args.simulation else SendInputBackend()
    ctl = Controller(backend, cfg)
    sounds = Sounds(os.path.join(ROOT, "assets", "sounds"), cfg.sounds,
                    volume=read_volume(VOLUME_FILE, cfg.sound_volume))
    # les DEUX mains sont détectées (demande de l'utilisateur) ; CPU mesuré ~7 % : marge suffisante
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "hand_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_hands=2))
    faces = {"lm": None}                       # détecteur de visage : créé au 1er passage à la tête seulement

    def face_landmarker():
        if faces["lm"] is None:
            faces["lm"] = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=os.path.join(ROOT, "models", "face_landmarker.task")),
                running_mode=vision.RunningMode.VIDEO, num_faces=1,
                output_facial_transformation_matrixes=True))   # orientation de la tête (souris à la tête)
            log.info("detecteur de visage pret (souris a la tete)")
        return faces["lm"]
    cam = Camera(cfg.camera_index, cfg.width, cfg.height).start()
    listener = None
    if args.voice:
        from .voice import VoiceListener, default_model_dir
        listener = VoiceListener(default_model_dir(ROOT)).start()
        listener.after_reopen = sounds.reopen      # micro rouvert = PortAudio relancé : la sortie des sons aussi
    from .ask import Asker
    asker = Asker()                            # « iris question » -> Whisper -> Claude Haiku
    if listener is not None:                   # sans la voix, Whisper ne sert à rien : pas chargé
        asker.preload()
    from .typer import Typer
    from .traducteur import Traducteur
    traducteur = Traducteur(asker.translate) if listener is not None else None   # « iris traducteur » (#14)
    typer = Typer(asker)                       # « iris type » -> Whisper -> texte écrit au curseur
    launcher = None
    app_messages = queue.Queue()
    pointer_requests = queue.Queue()           # clics sur « main / tête » (fil Qt) -> boucle principale
    quiet_requests = queue.Queue()             # clics sur « voix basse » (fil Qt) -> boucle principale
    camera_requests = queue.Queue()            # clics sur « caméra » (fil Qt) -> boucle principale
    conversation_requests = queue.Queue()      # clics sur « mode conversation » (fil Qt) -> boucle principale
    conversation = read_conversation(CONV_FILE)
    quiet_choice = read_quiet(QUIET_FILE)

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
    speaker = Speaker()                        # voix Windows : messages Discord et rappels
    # rappels et alarmes (issue #20) : « iris rappel » -> Whisper -> Haiku -> « envoie »
    from .ask import ask_claude
    from .reminders import PARSE_SYSTEM, Desk, Reminders
    desk = Desk(Reminders(os.path.join(ROOT, "reminders.json")).load(datetime.datetime.now()),
                None, sounds, bot, ask=lambda q: ask_claude(q, system=PARSE_SYSTEM),   # rappels sans voix (12/11)
                transcribe=lambda audio: asker._transcribe(audio, 16000))
    from .instruction import Instructeur        # « iris instruction » -> Whisper -> modèle local -> plan (#45)
    from .outils import Store
    instructeur = Instructeur(lambda audio: asker._transcribe(audio, 16000), launcher, desk,
                              routines=Store(os.path.join(ROOT, "routines.json")),     # non versionnés
                              favoris=Store(os.path.join(ROOT, "favoris.json")), bot=bot)
    asker.speaker = instructeur.speaker = speaker   # réponses lues si « lecture à voix haute » est cochée
    from .instruction_base import ensure_ollama  # #76 : Ollama démarré avec Iris, pas à la 1re instruction (8 s)
    threading.Thread(target=ensure_ollama, name="ollama-start", daemon=True).start()
    from .cvgen import Candidature              # « iris candidature » : Iris pilote CVGEN (plan-cvgen.md)
    candidature = Candidature(open_url=os.startfile)
    # micro / sourdine Discord : simple mémoire tant que l'appli tourne (demande de l'utilisateur).
    # Au lancement : micro allumé, pas de sourdine. Rien n'est enregistré ni lu dans Discord.
    discord_voice = {"mute": False, "deaf": False}

    # VS Code (micro de Claude, Entrée) : toujours envoyé pour de vrai, même en simulation,
    # sinon la dictée ne peut pas être essayée. Seules ces touches-là, et seulement vers VS Code.
    vscode_ctl = Controller(SendInputBackend(), cfg)
    log.info("demarrage (simulation=%s) camera=%s", args.simulation, cam.info)

    # Qt : l'interface tourne dans le fil principal, caméra + MediaPipe + Core dans un fil à part.
    from .app_outils import set_app_icon, set_app_identity
    set_app_identity()                         # barre des tâches : « Iris » et son logo, pas Python
    qt = QApplication.instance() or QApplication([])
    set_app_icon(qt)
    from .reglages import LECTURE_FILE, SECTION_FILE, read_flag
    lecture = read_flag(LECTURE_FILE, False)   # lecture à voix haute : décochée par défaut
    speaker.allowed = lecture
    view_win = PreviewWindow(pointer=cfg.pointer, quiet=quiet_choice, volume=sounds.mixer.volume, lecture=lecture,
                             section_file=SECTION_FILE)
    volume_requests = queue.Queue()            # clics sur « volume d'Iris » (fil Qt) -> boucle principale
    lecture_requests = queue.Queue()           # clics sur « lecture à voix haute » (fil Qt) -> boucle principale
    # une carte de réglage cliquée (fil Qt) -> la file de la boucle principale qui l'applique (jamais Core ici)
    setting_queues = {"souris": pointer_requests, "camera": camera_requests, "conversation": conversation_requests,
                      "voix_basse": quiet_requests, "volume": volume_requests, "lecture": lecture_requests}
    setting_actions = {}                       # réglages sans file : « son » (rempli plus bas)

    def on_setting(rid):
        log.info("accueil : carte %s", rid)
        if rid in setting_queues:
            setting_queues[rid].put(1)
        elif rid in setting_actions:
            setting_actions[rid]()
        else:
            log.warning("accueil : reglage inconnu %s", rid)
    view_win.reglage_clicked.connect(on_setting)
    stop = threading.Event()
    bridge = Bridge()
    bridge.lecture.connect(view_win.set_lecture)
    bridge.quiet.connect(view_win.set_quiet)
    bridge.camera.connect(view_win.set_camera)
    bridge.conversation.connect(view_win.set_conversation)
    view_win.set_conversation(conversation)
    if listener is not None:
        listener.conversation = conversation
    bridge.iris_volume.connect(view_win.set_volume)
    bridge.pointer.connect(view_win.set_pointer)          # choix fait à la voix : le bouton suit
    bridge.frame.connect(view_win.set_frame)   # file d'attente Qt : passe d'un fil à l'autre
    # panneau « Consommation » de la page d'accueil : mesuré seulement quand la page est visible
    live = {"detect_hz": DETECT_MAX_FPS}       # écrit par la boucle, lu par le fil de mesure

    def model_info():
        return {"whisper": asker._whisper is not None, "detect_hz": live["detect_hz"],
                "voice_on": listener is not None,
                "free_awake": listener is not None and time.perf_counter() < getattr(listener, "_free_until", 0)}

    bridge.stats.connect(view_win.set_stats)
    bridge.home.connect(view_win.set_home)
    from .stats import run_sampler
    threading.Thread(target=run_sampler, args=(lambda: view_win.visible_flag, bridge.stats.emit, model_info, stop),
                     name="mesures", daemon=True).start()
    glass = GlassOverlay("ui")                 # île, logo, pastille Discord : visibles dans les partages
    cursor_glass = GlassOverlay("cursor")      # curseur de la main + loupe : jamais dans les captures
    bridge.state.connect(glass.set_state)
    bridge.state.connect(cursor_glass.set_state)
    stop_btn = StopButton()                    # arrêt d'urgence, en bas à droite
    eye_btn = EyeButton(stop_btn)              # œil : montrer / masquer l'overlay dans les partages
    repair_btn = RepairButton()                # tout en bas à gauche : réparer le son (micro figé)

    restart = {"on": False}                    # sortie pour redémarrer : ni « bye » au bot, ni arrêt voulu

    def repair_sound():
        """Fil « reparation » : le message passe par la queue de la boucle (jamais Core ici)."""
        from . import audio_repair
        if listener is None:
            app_message("VOIX DESACTIVEE : rien a reparer")
            return
        app_message("REPARATION DU SON…")
        try:
            msg = audio_repair.repair(listener.reopen, listener.heard_since)
        except Exception:
            log.exception("reparation du son")
            msg = "REPARATION DU SON : ERREUR"
        if msg.startswith("MICRO NON ROUVERT"):
            # plus rien à faire sans redémarrer : Iris quitte SANS arrêt voulu, le gardien (ou le bot) la relance
            app_message("MICRO NON ROUVERT : Iris redemarre…")
            log.error("micro non rouvert : redemarrage demande")
            time.sleep(3)
            restart["on"] = True
            bridge.done.emit()
            return
        app_message(msg)
        bridge.repair_done.emit()

    def on_repair():
        log.info("bouton reparer le son appuye%s", " (deja en cours, ignore)" if repair_btn.busy else "")
        if repair_btn.busy:
            return
        repair_btn.set_busy(True)
        view_win.set_repair_busy(True)
        threading.Thread(target=repair_sound, name="reparation", daemon=True).start()

    repair_btn.triggered.connect(on_repair)
    setting_actions["son"] = on_repair         # carte « Son : réparer » de l'accueil : même chemin que le bouton
    bridge.repair_done.connect(lambda: repair_btn.set_busy(False))
    bridge.repair_done.connect(lambda: view_win.set_repair_busy(False))

    def show_in_captures(visible):
        for w in (glass, stop_btn):
            set_capture_visible(w, visible)
        log.info("overlay %s dans les partages d'ecran", "visible" if visible else "masque")

    eye_btn.toggled.connect(show_in_captures)
    bridge.done.connect(qt.quit)

    def hide_all():
        """Cache toutes les fenêtres d'Iris (aperçu, verres, boutons). Avant, au STOP, elles restaient figées
        à l'écran tant que le processus n'était pas sorti (parfois plusieurs minutes)."""
        for w in (view_win, glass, cursor_glass, stop_btn, eye_btn, repair_btn):
            try:
                w.hide()
            except RuntimeError:               # fenêtre déjà détruite
                pass

    def start_exit_guard(delay_s=EXIT_GUARD_S):
        """Sortie forcée si l'arrêt propre n'a pas abouti à temps (fil bloqué, boucle Qt qui ne rend pas la main)."""
        def guard():
            time.sleep(delay_s)
            log.warning("arret non abouti apres %.0f s : sortie forcee", delay_s)
            force_exit(ctl)
        threading.Thread(target=guard, name="sortie", daemon=True).start()

    def emergency(source):
        """STOP : tout relâcher tout de suite (sans attendre le moteur), puis quitter."""
        if not stop.is_set():
            log.info("STOP (%s)", source)
        stop.set()
        ctl.release_all()
        bot.bye()                              # arrêt voulu : le bot ne relance pas Iris
        from . import garde
        garde.mark_stop()                      # ni le gardien
        hide_all()                             # rien ne reste figé à l'écran pendant l'arrêt
        start_exit_guard()
        qt.quit()

    glass.closed.connect(lambda: emergency("verre ferme"))
    cursor_glass.closed.connect(lambda: emergency("verre ferme"))
    stop_btn.closed.connect(lambda: emergency("bouton ferme"))
    view_win.quit_clicked.connect(lambda: emergency("bouton fermer Iris de l'accueil"))
    stop_btn.triggered.connect(lambda: emergency("bouton STOP"))
    qt.aboutToQuit.connect(stop.set)

    def show(img):
        bridge.frame.emit(img)

    engine = Engine(SimpleNamespace(
        cfg=cfg, core=core, cam=cam, tracker=tracker, landmarker=landmarker, faces=faces,
        face_landmarker=face_landmarker, listener=listener, asker=asker, typer=typer, traducteur=traducteur, instructeur=instructeur, candidature=candidature, launcher=launcher,
        app_messages=app_messages, app_message=app_message, pointer_requests=pointer_requests, bot=bot,
        quiet_requests=quiet_requests, camera_requests=camera_requests,
        conversation_requests=conversation_requests, lecture_requests=lecture_requests, lecture=lecture, conversation=conversation, quiet_choice=quiet_choice, volume_requests=volume_requests,
        speaker=speaker, desk=desk, quota=Quota(), discord_voice=discord_voice, sounds=sounds, ctl=ctl, vscode_ctl=vscode_ctl,
        bridge=bridge, view_win=view_win, show=show, args=args, live=live, stop=stop))

    def run_engine():
        try:
            engine.run()
        except Exception:
            log.exception("erreur dans la boucle principale")
        finally:
            bridge.done.emit()

    worker = threading.Thread(target=run_engine, name="moteur", daemon=True)
    worker.start()
    from . import garde
    threading.Thread(target=garde.run_beat, args=(live, stop), name="battement", daemon=True).start()
    threading.Thread(target=watch_engine, args=(live, stop, os.path.join(ROOT, "logs", "blocage.txt")),
                     name="surveillance", daemon=True).start()
    view_win.show()
    glass.show()
    cursor_glass.show()
    stop_btn.show()
    eye_btn.show()
    repair_btn.show()
    sink = KeySink()
    sink.show()
    from . import vscode
    vscode.SINK_HWND = int(sink.winId())
    qt.exec()
    stop.set()
    hide_all()
    start_exit_guard()                         # aussi pour une sortie qui ne vient pas du STOP
    if not restart["on"]:
        bot.bye()
    worker.join(timeout=3)
    if worker.is_alive():      # moteur bloqué : tout est déjà relâché, on quitte quand même
        log.warning("moteur bloque a l'arret : sortie forcee")
    force_exit(ctl)


EXIT_GUARD_S = 5.0


def force_exit(ctl, exit=os._exit):
    """Sortie franche : un fil resté ouvert (écoute du micro, Whisper) gardait le processus en vie, avec
    l'overlay figé à l'écran et plusieurs motionzero à la fois. Tout est relâché avant."""
    try:
        ctl.release_all()
    except Exception:
        _log.exception("relachement a l'arret")
    logging.shutdown()
    exit(0)
