"""Application : caméra -> points de la main -> machine à états -> souris/clavier : méthodes de Engine (EcouteMixin, découpé de app.py, #52)."""
import datetime
import logging
import queue


from .core import Mode
from .power import power_actions
from .fenetre import window_actions
from .sounds import is_failure
from .vscode import foreground_exe

from .app_outils import (CONFIRM_WORDS, CONV_FILE, ERROR_NOTICE, POINTER_FILE, QUIET_FILE, QUOTA_FILE, VOLUME_FILE, VOLUME_STEPS, cam_down, cand_panel, detect_period, drain, last_tab, lower_priority, next_quiet, next_volume, note_error, pick_toast, plan_card, read_conversation, read_pointer, read_quiet, read_volume, reminder_shown, top_shown, watch_engine, write_pointer)  # noqa: F401
from .app_actions import (bot_absent, bot_events, discord_actions, discord_command, discord_spoken, open_actions, question_actions, type_actions, vscode_actions)  # noqa: F401

_log = logging.getLogger("motionzero")


class EcouteMixin:

    # --- 2. ce qui arrive des autres fils et services (toujours via des files : jamais Core touché ailleurs) ---
    def background(self, t):
        d, core = self.d, self.d.core
        acts = []
        if d.listener is not None:
            speech = d.listener.last_speech_t
            acts += core.dictation_tick(t, speech) + core.ask_tick(t, speech)
            if core.dictating and t - core.dictation_t0 > 2.0 and t - self.mic_check_t >= 0.5:
                self.mic_check_t = t
                from .vscode import claude_mic_state
                if claude_mic_state() is False:      # Claude a coupé son micro tout seul : Iris suit
                    _log.info("micro Claude coupe par Claude : fin de la dictee")
                    core.claude_mic_stopped(t)
            acts += core.type_tick(t, speech) + core.open_tick(t, speech)
        if getattr(d, "typer", None) is not None:
            for ok in drain(d.typer.done):    # texte de « iris type » écrit (fil du typer) : la confirmation part
                core.type_written(t, ok)
                _log.info("iris type : %s", "texte ecrit, envoie / annule 4 s" if ok else "rien compris")
        for msg in drain(d.app_messages):
            core.last_gesture = (msg, t)
        for _ in drain(d.pointer_requests):   # bouton « main / tête » de l'accueil (fil Qt)
            acts += core.set_pointer_toggle(t)
        self._quiet(t)
        self._camera()
        self._conversation()
        self._volume()
        if t - self.chrome_check_t >= 0.3:
            self.chrome_check_t = t           # le mode Chrome suit Chrome au premier plan (14/11)
            acts += core.front_app(foreground_exe(), t)
        acts += bot_events(d.bot, core, d.speaker, d.discord_voice, t, d.listener)
        d.desk.events(core, t)
        if getattr(d, "instructeur", None) is not None:
            acts += d.instructeur.events(core, t)   # « iris instruction » : plan prêt, étapes, Discord
        if getattr(d, "candidature", None) is not None:
            acts += d.candidature.events(core, t)   # « iris candidature » : réponses de CVGEN
        return acts

    # --- 3. voix ---
    def listen(self, t):
        d, core, listener = self.d, self.d.core, self.d.listener
        acts = []
        if listener is not None:
            if t < core.calendar_until:
                listener.grammar = "calendrier"   # jours, mois, nombres : seulement calendrier ouvert
            elif core.cand_on(t):             # « iris candidature » : ses mots seulement (souris : allumée)
                listener.grammar = "candidature_souris" if core.mouse or core.dragging else "candidature"
            elif core.mode == Mode.CHROME:
                listener.grammar = "chrome"
            else:                             # mots de la souris : seulement souris allumée ou bouton tenu
                # mode focus : commandes sans « iris », clic compris (16/11)
                listener.grammar = "souris" if core.mouse or core.dragging or core.focus_on(t) else "base"
            # juste après une dictée : « envoie / annule » attendus, reconnus plus facilement (seuil normal, et un
            # texte libre vide les confirme : mesuré, juste après la coupure du micro il est souvent vide)
            listener.relaxed = CONFIRM_WORDS if core.confirming(t) else frozenset()
            listener.bypass = core.bypass_on(t)   # « iris bypass » : seuils plus bas (un booléen, lu par le fil voix)
            if t - listener.iris_heard_t < 0.5:
                core.freeze_for_voice(t)      # « iris » en cours de prononciation : curseur figé
            events = listener.poll()
            if events:
                core.top_shown = top_shown(d, t)
                core.reminder_shown = reminder_shown(d)
            for ev in events:
                new = core.voice(ev.word, ev.t_end, t_start=ev.t_start)
                acts += new
                accepted = core.last_word and core.last_word[2]
                _log.info("voix %s (%.2f) %s", ev.word, ev.conf, "acceptee" if accepted else "ignoree (ecoute fermee)")
                if ev.word == "iris" and accepted:
                    d.sounds.play("ECOUTE")
                elif accepted and not any(a[0] in ("mode", "mouse") for a in new):
                    d.sounds.play("OK")       # commande comprise (un changement de mode a son propre son)
            rej = listener.last_rejected
            if rej is not None and rej is not self.last_rej_seen:
                self.last_rej_seen = rej
                if core.listening(t):         # après « iris » seulement : la conversation reste muette
                    d.sounds.play("NON")
            if core.dictating and t - self.last_level_log >= 1.0:
                self.last_level_log = t
                _log.debug("dictee : micro rms %.0f (bruit de fond %.0f), parole il y a %.1f s",
                         listener.last_rms, listener.ambient, t - listener.last_speech_t)
        lg = core.last_gesture
        if lg is not None and lg is not self.last_fail_seen:
            self.last_fail_seen = lg
            if is_failure(lg[0]):
                d.sounds.play("NON")          # rien entendu, pas compris, réglage impossible…
        return acts

    def _volume(self):
        """Bouton « volume d'Iris » de l'accueil : appliqué, enregistré, et un son pour l'entendre."""
        d = self.d
        for _ in drain(getattr(d, "volume_requests", None) or queue.Queue()):
            vol = next_volume(d.sounds.mixer.volume)
            d.sounds.mixer.volume = vol
            write_pointer(VOLUME_FILE, str(vol))
            d.bridge.iris_volume.emit(vol)
            d.sounds.play("OK")
            _log.info("volume d'Iris : %d %%", round(vol * 100))

    def _camera(self):
        """Clics sur « caméra » : le fil caméra ferme / rouvre la webcam lui-même. Seulement boucle principale."""
        d = self.d
        for _ in drain(d.camera_requests):
            d.cam.paused = not d.cam.paused
            d.bridge.camera.emit(d.cam.paused)
            _log.info("camera %s (bouton)", "coupee" if d.cam.paused else "rallumee")

    def _conversation(self):
        """Clics sur « mode conversation » : enregistré, et le micro prévenu par un booléen. Boucle principale."""
        d = self.d
        for _ in drain(d.conversation_requests):
            d.conversation = not d.conversation
            write_pointer(CONV_FILE, "oui" if d.conversation else "non")
            if d.listener is not None:
                d.listener.conversation = d.conversation
            d.bridge.conversation.emit(d.conversation)
            _log.info("mode conversation %s", "coche" if d.conversation else "decoche")

    def _quiet(self, t):
        """Voix basse : choix de l'accueil (enregistré) et heure ; le micro est prévenu par un simple booléen."""
        d = self.d
        for _ in drain(d.quiet_requests):
            self.quiet_choice = next_quiet(self.quiet_choice)
            write_pointer(QUIET_FILE, self.quiet_choice)
            d.bridge.quiet.emit(self.quiet_choice)
            _log.info("voix basse : %s", self.quiet_choice)
            self.quiet_check_t = -1e9
        if d.listener is None or t - self.quiet_check_t < 1.0:
            return
        self.quiet_check_t = t
        from .voice import quiet_active
        on = quiet_active(self.quiet_choice, datetime.datetime.now().hour)
        if on != d.listener.quiet:
            d.listener.quiet = on
            _log.info("voix basse %s", "activee" if on else "desactivee")

    # --- 4. actions : chaque service prend les siennes et renvoie le reste ---
    def resolve(self, acts, t):
        d = self.d
        if d.listener is not None:
            if d.asker is not None and any(a[0] in ("ask_start", "type_start", "open_start") for a in acts):
                d.asker.warm()                # Whisper chargé pendant que tu parles (14/11 : 120 rechargements
                                              # de 1,5 à 3 s attendus APRÈS la dictée, après 10 min sans usage)
            acts = question_actions(acts, d.listener, d.asker)
            acts = type_actions(acts, d.listener, d.typer, d.sounds)
            acts = open_actions(acts, d.listener, d.launcher, d.asker, d.bot, d.app_message, d.desk,
                                getattr(d, "instructeur", None), getattr(d, "candidature", None))
        if getattr(d, "instructeur", None) is not None:
            acts = d.instructeur.actions(acts, d.core, t)
        if getattr(d, "candidature", None) is not None:
            acts = d.candidature.actions(acts, d.core, t)
        acts = d.desk.actions(acts, d.core, t)
        acts = discord_actions(acts, d.speaker)
        acts = power_actions(acts)
        acts = window_actions(acts)
        return vscode_actions(acts, d.core, d.vscode_ctl, d.sounds, t, d.discord_voice)
