"""Écoutes en cours : dictée Claude, question, frappe, phrase libre (ouvre, rappel…), confirmations. Méthodes de Core (découpé de core.py, #52) : seulement boucle principale."""

from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401


class EcouteMixin:

    # --- dictée Claude (VS Code) ---------------------------------------------
    def ask_confirm(self, kind, t, seconds):
        """Une question attend « envoie » / « annule » (sans « iris ») pendant `seconds`."""
        self.confirm_kind = kind
        self.confirm_until = t + seconds

    def confirming(self, t):
        return t < self.confirm_until

    def dictation_tick(self, t, last_speech_t):
        """Coupe le micro de Claude quand tu as fini de parler : silence de dictation_silence_s après ta
        dernière parole (la durée de la demande n'est pas limitée). Rien dit du tout : on abandonne."""
        if not self.dictating:
            return []
        c = self.cfg
        spoke = last_speech_t > self.dictation_t0 + c.dictation_echo_s
        if spoke and t - last_speech_t >= c.dictation_silence_s:
            self.dictating = False
            self.confirm_until = t + c.send_confirm_s
            self.confirm_kind = "claude"
            self.last_gesture = ("MICRO COUPE : dis ENVOIE ou ANNULE", t)
            return [("vscode_dictation",)]
        if not spoke and t - self.dictation_t0 >= c.dictation_no_speech_s:
            self.dictating = False
            self.last_gesture = ("RIEN ENTENDU : micro coupe", t)
            return [("vscode_dictation",)]
        return []

    def claude_mic_stopped(self, t):
        """Le micro de Claude s'est coupé sans Iris : fin de la dictée, sans renvoyer le raccourci."""
        if not self.dictating:
            return
        self.dictating = False
        self.confirm_until = t + self.cfg.send_confirm_s
        self.confirm_kind = "claude"
        self.last_gesture = ("MICRO COUPE : dis ENVOIE ou ANNULE", t)

    def freeze_for_voice(self, t):
        """Plus de gel du curseur sur « iris » (gênant, demande de l'utilisateur, 12/11) : le clic vocal vise
        désormais là où était le curseur quand la commande a commencé (voir _aim). Gardée pour la boucle."""
        return

    def _aim(self, ref_t, acts):
        """Ramène le curseur là où il était à l'instant ref_t (début de « iris clic ») avant de cliquer :
        pendant qu'on parle, la main ou la tête a pu bouger."""
        if not self.mouse or ref_t is None:
            return
        pos = None
        for tt, p in self.cursor_hist:
            if tt <= ref_t:
                pos = p
            else:
                break
        if pos is not None and pos != self.cursor:
            self.cursor = pos
            self._cursor_f = [float(pos[0]), float(pos[1])]
            acts.append(("move", *pos))

    def ask_tick(self, t, last_speech_t):
        """Fin de la question : comme la dictée, après un silence ; rien dit du tout : abandon."""
        if not self.asking:
            return []
        c = self.cfg
        spoke = last_speech_t > self.ask_t0 + c.dictation_echo_s
        if spoke and t - last_speech_t >= c.dictation_silence_s:
            self.asking = False
            self.last_gesture = ("QUESTION POSEE A IRIS", t)
            return [("ask_stop",)]
        if not spoke and t - self.ask_t0 >= c.dictation_no_speech_s:
            self.asking = False
            self.last_gesture = ("RIEN ENTENDU : question annulee", t)
            return [("ask_cancel",)]
        return []

    def type_tick(self, t, last_speech_t):
        """« iris type » : fin de la dictée après 2 s de silence. « envoie / annule » seuls sont acceptés dès la
        coupure (dits trop tôt, ils attendent le texte dans la file du typer), et encore type_confirm_s après
        l'apparition du texte (type_written)."""
        if not self.typing:
            return []
        c = self.cfg
        spoke = last_speech_t > self.type_t0 + c.dictation_echo_s
        if spoke and t - last_speech_t >= c.type_silence_s:
            self.typing = False
            self.confirm_until = t + TYPE_WAIT_S       # le temps que Whisper écrive le texte
            self.confirm_kind = "type"
            self.last_gesture = ("ECRITURE DU TEXTE...", t)
            return [("type_stop",)]
        if not spoke and t - self.type_t0 >= c.dictation_no_speech_s:
            self.typing = False
            self.last_gesture = ("RIEN ENTENDU : dictee annulee", t)
            return [("type_cancel",)]
        return []

    def type_written(self, t, ok):
        """Le typer a fini (lu dans la boucle principale) : texte écrit (ok) ou rien compris."""
        if self.confirm_kind != "type" or not self.confirming(t):
            return                            # déjà envoyé ou annulé pendant l'écriture
        if ok:
            self.confirm_until = t + self.cfg.type_confirm_s
            self.type_erase_until = t + TYPE_ERASE_S
            self.last_gesture = ("TEXTE ECRIT : ENVOIE ou ANNULE ?", t)
        else:
            self.confirm_until = -1e9
            self.last_gesture = ("RIEN COMPRIS : dictee annulee", t)

    def open_tick(self, t, last_speech_t):
        """« iris ouvre / ferme » : le nom est court, l'écoute se coupe après un court silence.
        Rien dit : abandon sans bruit pour « ferme » (il a déjà retiré la réponse affichée)."""
        if not self.opening:
            return []
        c = self.cfg
        kind = self.open_kind
        close = kind == "close"
        spoke = last_speech_t > self.open_t0 + c.dictation_echo_s
        # un message est une phrase : même silence que la dictée ; un nom (appli, salon) est court
        silence = c.type_silence_s if kind in ("message", "rappel", "instruction", "candq") else c.open_silence_s
        if spoke and t - last_speech_t >= silence:
            self.opening = False
            self.last_gesture = (OPEN_WAIT[kind], t)
            return [(OPEN_STOP[kind],)]
        if not spoke and t - self.open_t0 >= (c.close_no_speech_s if close else c.open_no_speech_s):
            self.opening = False
            if not close:
                self.last_gesture = ({"open": "RIEN ENTENDU : ouvre annule", "message": "RIEN ENTENDU : message annule",
                                      "salon": "RIEN ENTENDU : salon annule",
                                      "rappel": "RIEN ENTENDU : rappel annule",
                                      "timer": "RIEN ENTENDU : timer annule",
                                      "volume": "RIEN ENTENDU : volume inchange",
                                      "instruction": "RIEN ENTENDU : instruction annulee",
                                      "candq": "RIEN ENTENDU : question annulee"}[kind], t)
            return [("open_cancel",)]
        return []

    def _confirm(self, word, t):
        """Après la dictée : « envoie » (Entrée) ou « annule » (vide le champ). Pas besoin de dire « iris »."""
        self.last_word = (word, t, True)
        if word == "envoie":
            self.confirm_until = -1e9
            self.last_gesture = ("MESSAGE ENVOYE A CLAUDE", t)
            return [("vscode_keys", [["enter"]])]
        if word == "annule":
            self.confirm_until = -1e9
            self.last_gesture = ("MESSAGE EFFACE", t)
            return [("vscode_keys", [["ctrl", "a"], ["backspace"]])]
        if word == "claude":  # redicter : le nouveau texte s'ajoute à la suite
            self.confirm_until = -1e9
            return self.voice_claude(t)
        self.last_gesture = ("dis ENVOIE ou ANNULE", t)
        return []

    def voice_claude(self, t):
        self.dictating = True
        self.dictation_t0 = t
        self.last_gesture = (VOICE_LABELS["claude"], t)
        return [("vscode_dictation",)]
