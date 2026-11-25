"""Application : caméra -> points de la main -> machine à états -> souris/clavier : méthodes de Engine (AffichageMixin, découpé de app.py, #52)."""
import datetime
import logging


from .camera import OK
from .aide import help_view
from .overlay import render
from .volume import VIEW as VOLUME_VIEW
from .quota import write_shown
from .accueil import home_view, sensors as home_sensors
from .ui import clock_text

from .app_outils import (CONFIRM_WORDS, CONV_FILE, ERROR_NOTICE, POINTER_FILE, QUIET_FILE, QUOTA_FILE, VOLUME_FILE, VOLUME_STEPS, cam_down, cand_panel, detect_period, drain, last_tab, lower_priority, next_quiet, next_volume, note_error, pick_toast, plan_card, read_conversation, read_pointer, read_quiet, read_volume, reminder_shown, top_shown, watch_engine, write_pointer)  # noqa: F401
from .app_actions import (bot_absent, bot_events, discord_actions, discord_command, discord_spoken, open_actions, question_actions, type_actions, vscode_actions)  # noqa: F401

from .app_main import HOME_PERIOD_S, STALE_S

_log = logging.getLogger("motionzero")


class AffichageMixin:

    def after(self, acts):
        """Sons et journal des actions faites."""
        d = self.d
        for a in acts:
            if a[0] == "mode":
                core = d.core
                if not core.mode_auto:        # suivi de l'appli devant : pas de son à chaque Alt+Tab
                    d.sounds.play(a[1])
                _log.info("mode %s (%s)", a[1], core.mode_why or "?")
            elif a[0] == "quota":
                write_shown(QUOTA_FILE, a[1])
                if a[1]:
                    d.quota.force()
                _log.info("quota %s", "affiche" if a[1] else "masque")
            elif a[0] == "traducteur":
                if getattr(d, "traducteur", None) is None:
                    d.core.translating = False     # sans la voix, pas de Whisper : rien à faire
                elif a[1]:
                    d.traducteur.start()
                else:
                    d.traducteur.stop()
            elif a[0] == "pointer":
                write_pointer(POINTER_FILE, a[1])
                d.bridge.pointer.emit(a[1])
                d.sounds.play("MODE")
                _log.info("souris pilotee par : %s", a[1])
            elif a[0] == "mouse":
                d.sounds.play("SOURIS" if a[1] else "REPOS")
                _log.info("souris %s", "allumee" if a[1] else "eteinte")
            elif a[0] == "scroll":
                _log.debug("scroll %s", a[1])   # ~35 000 lignes en 12 jours : noyait les erreurs (#49)
            elif a[0] == "hotkey":
                _log.info("touches %s", "+".join(a[1]))
            elif a[0] in ("key", "click"):
                _log.info("%s %s (%s)", a[0], a[1], d.core.last_gesture[0] if d.core.last_gesture else "")

    # --- 5. affichage ---
    def publish(self, view, t):
        d, core, cam = self.d, self.d.core, self.d.cam
        if self.pts is not None or self.frame_seen:
            self.last_view = view.copy()
        status = cam.status if t - self.last_frame_t <= STALE_S else (cam.status if cam.status != OK else "perdue")
        # fenêtre d'aperçu réduite : on ne dessine plus l'image (20 fois par seconde pour rien)
        if d.view_win.visible_flag or d.args.screenshot:
            self.shown = render(view, core, d.tracker.tracks if self.pts is not None else [], self.fps,
                                d.args.simulation, status, d.tracker.active_id, voice_on=d.listener is not None)
            d.show(self.shown)
        if core.pointer == "tete" and core.mouse and t - self.speed_log_t >= 5.0 and core.head_speeds:
            self.speed_log_t = t                  # réglage de la précision (15/11) : vitesses réelles de la tête
            v = sorted(core.head_speeds)
            core.head_speeds.clear()
            _log.info("tete vitesse : mediane %.3f, 90 %% %.3f, max %.3f (lent < %.2f, rapide > %.2f)",
                      v[len(v) // 2], v[int(len(v) * 0.9)], v[-1], d.cfg.head_speed_lo, d.cfg.head_speed_hi)
        if d.view_win.visible_flag and t - self.home_t >= HOME_PERIOD_S:
            self.home_t = t
            d.bridge.home.emit(self.home(status, t))
        prog = core.progress()
        # île : la dernière chose comprise (ou refusée), la plus récente des deux
        rej = d.listener.last_rejected if d.listener is not None else None
        # erreurs (#51) : montrées comme le reste, 6 s au plus. Caméra en panne (#48) : plus de texte dans
        # l'île (24/11, trop long) : une caméra barrée qui clignote en bas à gauche (« cam_down »)
        err = ERROR_NOTICE["notice"]
        if err and t - err[1] > 6.0:
            err = None
        toast = pick_toast(core.last_gesture, rej, err)
        d.bridge.state.emit({
            "show_cursor": core.mouse and not core.scrolling(t),  # défile : curseur dans la jauge
            "mouse": core.mouse,
            "cursor": core.cursor,
            "progress": prog[1] if prog else 0.0,
            # perdu = ce qui pilote : le visage à la tête (la main n'y est jamais suivie)
            "lost": self.face_lost if core.pointer == "tete" else self.pts is None,
            "pointer": core.pointer,
            "arming": core.mouse and not core.armed,
            # main fantôme : où est la main tant que le curseur attend qu'elle vienne au centre
            "ghost": core.ghost() if self.pts is not None else None,
            # « défile » : jauge au bord droit, la main monte / descend dedans
            "scroll_gauge": core.scroll_gauge(t),
            "volume": VOLUME_VIEW.state(t, core.opening and core.open_kind == "volume"),
            "mode": core.mode,
            "front": getattr(core, "front_exe", None),   # l'appli devant, affichée en haut (24/11)
            "focus": core.focus_on(t),
            "bypass": core.bypass_on(t),
            "candidature": core.cand_on(t),
            "cam_down": cam_down(status),
            "dragging": core.dragging,
            "dictating": core.dictating,
            "typing": core.typing or core.opening,
            "confirming": core.confirming(t),
            "listening": core.listening(t),
            "toast": toast[0] if toast else None,
            # main verte 0,5 s : une commande vocale vient d'être comprise (pas « iris » seul)
            "ok_flash": bool(core.last_word and core.last_word[2] and core.last_word[0] != "iris"
                             and t - core.last_word[1] < 0.5),
            "toast_age": t - toast[1] if toast else 1e9,
            "qa": d.asker.snapshot() if d.listener is not None else None,
            "discord": (d.discord_voice["mute"], d.discord_voice["deaf"]),
            "reminders": d.desk.state(t, calendar_open=t < core.calendar_until),
            "clock": clock_text(datetime.datetime.now()) if t < core.clock_until else None,
            "quota": self._quota(t),
            "subs": d.traducteur.snapshot() if getattr(d, "traducteur", None) is not None else None,
            "plan": plan_card(d, t),
            "cand_panel": cand_panel(d, t),
            "help": help_view(core.mode, t < core.calendar_until, core.confirming(t)) if t < core.help_until else None,
        })


    def _quota(self, t):
        """Texte du quota Claude (en haut à droite), ou None s'il est masqué. Lu en fond, jamais bloquant."""
        q, core = getattr(self.d, "quota", None), self.d.core
        if q is None or not core.quota_shown:
            return None
        q.tick(t, True)
        return q.lines()

    def home(self, cam_status, t):
        """Contenu de la page d'accueil (accueil.home_view). Le gardien est relu toutes les 2 s seulement."""
        d, core, lis = self.d, self.d.core, self.d.listener
        if t - self.guard_t >= 2.0:
            self.guard_t = t
            from .garde import guard_running
            try:
                self.guard_on = guard_running()
            except OSError:
                self.guard_on = False
        muted = bool(lis is not None and lis.muted)
        stalled = bool(lis is not None and getattr(lis, "t_stream0", None) is not None
                       and t - max(getattr(lis, "last_block_t", 0.0), lis.t_stream0) > 3.0)
        sensors = home_sensors(
            "ok" if cam_status == OK else cam_status, voice_on=lis is not None, mic_muted=muted,
            mic_stalled=stalled, whisper=d.asker._whisper is not None,
            bot_enabled=d.bot.enabled, bot_connected=d.bot.connected, guard=self.guard_on)
        return home_view(
            core.mode, mouse=core.mouse, pointer=core.pointer, listening=core.listening(t),
            dictating=core.dictating, confirming=core.confirming(t), calendar_open=t < core.calendar_until,
            mic_muted=muted, voice_on=lis is not None, sensor_list=sensors, feed=list(core.feed),
            rejected=lis.last_rejected if lis is not None else None, now=t)
