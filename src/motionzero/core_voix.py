"""Aiguillage des mots reconnus : confirmation, calendrier, aide, stop, candidature, sans « iris », réveil. Méthodes de Core (découpé de core.py, #52) : seulement boucle principale."""

from .cvgen import WORDS as CAND_WORDS
from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401


class VoixMixin:

    # --- voix ----------------------------------------------------------------
    def listening(self, t):
        """L'écoute est ouverte après « iris », ou tant que la bulle / le menu (main immobile) sont affichés."""
        # (après une dictée, envoie / annule / claude sont traités à part : l'écoute n'est pas ouverte
        # pour autant, sinon n'importe quel mot seul serait exécuté pendant 30 s)
        return self.mode != Mode.DISABLED and (t < self.listen_until or self.bubble is not None
                                               or self.menu.is_open)

    def focus_on(self, t):
        """Mode focus : plus besoin de dire « iris » (pas de conversation à côté). Jamais en pause."""
        return self.mode != Mode.DISABLED and t < self.focus_until

    def voice(self, word, t, t_start=None):
        """Un mot reconnu (déjà filtré : dit seul). Renvoie les actions.
        Ordre des étapes = ordre de priorité : chacune traite le mot (et renvoie les actions) ou passe (None)."""
        word = ALIASES.get(word, word)
        if self.dictating or self.asking or self.typing or self.opening:
            # dictée ou question en cours : tes mots sont du texte, pas des commandes. Noté refusé : le journal
            # disait « acceptee » (d'après le mot d'avant), ce qui faussait les comptes (14/11)
            self.last_word = (word, t, False)
            return []
        acts = []
        for step in (self._v_confirm, self._v_calendar, self._v_help, self._v_stop, self._v_candidature, self._v_without_iris, self._v_wake, self._v_resume):
            done = step(word, t, t_start, acts)
            if done is not None:
                lw = self.last_word
                if word not in (WAKE_WORD, "annule") and lw and lw[0] == word and lw[2]:
                    self.type_erase_until = -1e9   # autre commande faite : « iris annule » reprend son sens habituel
                return done
        if not (self.listening(t) or self.focus_on(t)):
            self.last_word = (word, t, False)  # entendu mais écoute fermée : ignoré
            self.last_gesture = (f'"{word}" ignore : dis IRIS avant', t)
            return acts
        return self._v_command(word, t, acts)

    # --- étapes de voice() : chacune renvoie la liste d'actions si elle traite le mot, sinon None ---
    def _v_confirm(self, word, t, t_start, acts):
        """Juste après « iris type / claude / rappel » : envoie / annule (et claude) marchent sans « iris »."""
        if not self.confirming(t):
            if word == "annule" and t < self.type_erase_until and self.listening(t):
                # « iris annule » juste après une dictée : n'efface que la dictée (dans VS Code, l'« annule »
                # habituel vide tout le champ : mesuré le 12/11, Ctrl+A puis Retour arrière)
                self.type_erase_until = self.listen_until = -1e9
                self.last_word = (word, t, True)
                self.last_gesture = ("TEXTE EFFACE", t)
                return [("type_erase",)]
            return None
        if self.confirm_kind == "type" and word != WAKE_WORD:
            # tout autre mot : le texte reste tel quel et le mot est traité normalement
            self.confirm_until = -1e9
            if word in ("envoie", "annule"):
                self.last_word = (word, t, True)
                self.last_gesture = ("TEXTE ENVOYE" if word == "envoie" else "TEXTE EFFACE", t)
                return [("type_send",)] if word == "envoie" else [("type_erase",)]
        elif self.confirm_kind == "claude" and word in ("envoie", "annule", "claude"):
            # aucun verrou : toutes les autres commandes « iris + … » restent utilisables
            return self._confirm(word, t)
        elif self.confirm_kind == "instruction" and word in ("envoie", "envoyé", "annule"):
            self.confirm_until = -1e9
            self.last_word = (word, t, True)
            return [("instruction_non",)] if word == "annule" else [("instruction_ok",)]
        elif self.confirm_kind == "rappel" and word in ("envoie", "annule"):
            self.confirm_until = -1e9
            self.last_word = (word, t, True)
            return [("rappel_ok",)] if word == "envoie" else [("rappel_non",)]
        return None

    def _v_calendar(self, word, t, t_start, acts):
        """Calendrier ouvert : ses mots marchent sans « iris » ; ferme / merci / ok / stop le ferment."""
        if t < self.calendar_until:
            if word in CAL_WORDS:
                self.calendar_until = t + CAL_IDLE_S
                self.last_word = (word, t, True)
                self.listen_until = -1e9
                return [("cal", word)]
            if word in ("ferme", "merci"):
                self.calendar_until = -1e9
                self.last_word = (word, t, True)
                self.listen_until = -1e9
                self.last_gesture = ("CALENDRIER FERME", t)
                return [("cal_close",)]
            if word == "stop":
                self.calendar_until = -1e9
                acts.append(("cal_close",))       # puis le « stop » habituel
        elif (word in CAL_WORDS and not (self.mode == Mode.CHROME and word in CHROME_KEYS)
              and not (word in EDITOR_TABS and (self.listening(t) or self._in_vscode()   # onglets de VS Code
                                                or (t < self.repeat_until and word in self.repeat_acts)))):
            self.last_word = (word, t, False)     # calendrier fermé : ces mots ne font rien, sans bruit
            return acts
        return None

    def _v_help(self, word, t, t_start, acts):
        """Aide affichée : « ferme » / « merci » la ferment sans « iris » ; « stop » aussi (puis le stop habituel)."""
        if t >= self.help_until:
            return None
        if word in ("ferme", "merci"):
            self.help_until = -1e9
            self.last_word = (word, t, True)
            self.listen_until = -1e9
            self.last_gesture = ("AIDE FERMEE", t)
            return acts
        if word == "stop":
            self.help_until = -1e9
        return None

    def _v_stop(self, word, t, t_start, acts):
        """« stop » : toujours écouté, prioritaire. « lâche » : un bouton tenu doit toujours pouvoir être relâché."""
        if word == "stop":
            acts += [("release_all", "force"), ("alarm_stop",)]   # une alarme qui sonne se tait aussi
            self.dragging = False                 # « stop » : relâche aussi le bouton d'« agrippe »
            self._quiet()
            scrolling = t < self.voice_scroll_until
            self.voice_scroll_until = self.listen_until = -1e9
            if scrolling:                     # « stop » pendant le défilement : fin du défilement seulement
                self._end_scroll(t)
            elif self.mouse:
                self.set_mouse(False, t, acts)  # souris allumée : « stop » l'éteint seulement, le mode reste
            elif self.mode == Mode.READING:     # Chrome : le mode suit Chrome devant, « stop » ne le quitte plus
                self.set_mode(Mode.NEUTRAL, t, acts, why="stop")
            self.last_gesture = ("STOP", t)
            self.last_word = (word, t, True)
            return acts
        if word == "agrippe" and self.dragging:   # redit : relâche, toujours écouté (bouton tenu)
            self.dragging = False
            self.last_word = (word, t, True)
            self.last_gesture = ("BOUTON LACHE", t)
            return [("release", "mouse", "left")]
        return None

    def cand_on(self, t):
        return self.mode != Mode.DISABLED and t < self.cand_until

    def _v_candidature(self, word, t, t_start, acts):
        """Mode candidature : ses mots sans « iris » ; « candidature » (seul ou après « iris ») l'éteint."""
        if not self.cand_on(t):
            return None
        if word == "question":                # #46 : la question du formulaire est enregistrée (Whisper)
            self.cand_until = t + CAND_IDLE_S
            self._heard_alone(word, t, "")
            self.last_gesture = (self._start_open("candq", t, acts, "QUESTION : dis la question du formulaire"), t)
            return acts
        if word in CAND_WORDS:
            self.cand_until = t + CAND_IDLE_S
            self._heard_alone(word, t, f"CANDIDATURE : {word.upper()}")
            return [("cand", word)]
        if word == "candidature":
            self.cand_until = -1e9
            self._heard_alone(word, t, "CANDIDATURE ETEINTE")
            return [("cand_off",)]
        if word == "souris":                  # seul mot de base gardé dans le mode (sans « iris »)
            self._heard_alone(word, t, "")
            self.last_gesture = (self._cmd_mouse(word, t, acts), t)
            return acts
        return None

    def _cmd_candidature(self, word, t, acts):
        """« iris candidature » : Iris pilote CVGEN (plan-cvgen.md) ; redit, éteint ; seul après 30 min."""
        self.cand_until = t + CAND_IDLE_S
        acts.append(("cand", "état"))
        return "CANDIDATURE : cherche, etat, offres"

    def _heard_alone(self, word, t, label):
        """Mot accepté sans « iris » : l'écoute se ferme et le curseur est libéré."""
        self.last_word = (word, t, True)
        self.listen_until = -1e9
        self.freeze_until = -1e9
        self.last_gesture = (label, t)

    def _v_without_iris(self, word, t, t_start, acts):
        """Mots acceptés sans « iris » selon le contexte : répétition (skip, efface…), mode Chrome, souris allumée."""
        if t < self.repeat_until:
            if word in self.repeat_acts:      # « skip, skip, skip » : chaque mot relance la fenêtre de 2 s
                self.repeat_until = t + self.cfg.repeat_s
                self.last_word = (word, t, True)
                self.last_gesture = self.repeat_acts[word][1]
                return list(self.repeat_acts[word][0])
            self.repeat_until = -1e9          # autre mot : fin de la répétition, comportement habituel
        chrome = self.mode == Mode.CHROME
        if word in EDITOR_TABS and self._in_vscode():
            # VS Code devant : onglet suivant / précédent sans « iris » (ne servent qu'à ça hors Chrome, 14/11)
            label = "ONGLET " + ("SUIVANT" if word == "suivant" else "PRECEDENT") + " (VS Code)"
            self._heard_alone(word, t, label)
            self._arm_repeat(word, t, [("editor_tab", EDITOR_TABS[word])])
            return [("editor_tab", EDITOR_TABS[word])]
        if word in ("ferme", "merci") and (self.top_shown or t < self.clock_until):
            # quelque chose est affiché en haut (réponse, rappel, liste, heure) : il part, sans « iris », partout
            # (#34 en Chrome ; 14/11 partout). En Chrome, « ferme » redit ensuite ferme l'onglet.
            self._heard_alone(word, t, "AFFICHAGE RETIRE (redis FERME pour l'onglet)" if chrome and word == "ferme"
                              else "AFFICHAGE RETIRE")
            acts += [("rappel_merci",), ("ask_close",)]
            self.clock_until = -1e9
            return acts
        if word == "plus tard" and self.reminder_shown:
            self._heard_alone(word, t, VOICE_LABELS["plus tard"])     # rappel affiché : « plus tard » sans « iris »
            return [("rappel_tard",)]
        if chrome and word in ("skip", "back", "space"):
            # mode Chrome : vidéo (±10 s, pause) sans « iris » (demande de l'utilisateur, 12/11)
            self._heard_alone(word, t, VOICE_LABELS[word])
            return [("hotkey", VOICE_HOTKEYS[word])]
        mouse = self.mouse or self.dragging
        if mouse and word in ("agrippe", "scroll"):
            return self._v_command(word, t, acts)   # souris : glisse / scroll sans « iris » (15/11)
        if (chrome and word in ("clic", "double")) or (mouse and word in ("clic", "double", "menu")):
            # mode Chrome ou souris allumée : clic, double clic (et clic droit en souris) sans « iris » (12/11)
            # « iris clic » : on vise le début de « iris » ; « clic » seul : le début du mot
            ref = self.wake_t if self.listening(t) else (t_start if t_start is not None else t)
            self._heard_alone(word, t, VOICE_LABELS[word])
            self._aim(ref, acts)
            self._click(word, t, acts)
            return acts
        if chrome and word in CHROME_KEYS:
            # ses mots ne sont écoutés qu'en mode Chrome (voir voice.GRAMMARS), donc jamais pris ailleurs
            self._heard_alone(word, t, CHROME_LABELS[word])
            acts.append(("chrome_keys", CHROME_KEYS[word]))
            if word == "recherche":
                self.typing = True
                self.type_t0 = t
                acts.append(("type_start",))
            return acts
        return None

    def _v_wake(self, word, t, t_start, acts):
        if word != WAKE_WORD:
            return None
        self.wake_t = t_start if t_start is not None else t
        self.listen_until = t + self.cfg.listen_s
        if self.mode == Mode.DISABLED:
            # en pause, « iris » seul ne réveille plus (il était dit dans la conversation) : il faut « iris reprise »
            self.last_word = (word, t, True)
            self.last_gesture = ("PAUSE : dis IRIS REPRISE", t)
            return acts
        self.last_word = (word, t, True)
        self.last_gesture = ("IRIS : ECOUTE OUVERTE", t)
        return acts

    def _v_resume(self, word, t, t_start, acts):
        """En pause : seul « iris reprise » réactive ; tout autre mot est ignoré."""
        if self.mode != Mode.DISABLED:
            return None
        if word == "reprise" and t < self.listen_until:
            self.listen_until = -1e9
            self.set_mode(Mode.NEUTRAL, t, acts, why="reprise")   # Chrome devant : retrouvé au contrôle suivant
            self.last_word = (word, t, True)
            self.last_gesture = ("REPRISE", t)
        else:
            self.last_word = (word, t, False)
        return acts

    def _v_command(self, word, t, acts):
        if self.focus_on(t) and word != "focus":
            self.focus_until = t + FOCUS_IDLE_S   # chaque commande prolonge le mode focus
        if self.bypass_on(t) and word != "bypass":
            self.bypass_until = t + BYPASS_IDLE_S # pareil pour le bypass
        return self._v_command_run(word, t, acts)

    def _v_command_run(self, word, t, acts):
        """« iris » + un mot : une seule commande par « iris » (avant, la fenêtre restait ouverte 8 s et un mot de
        la conversation qui suivait — « colle », « chrome » — était exécuté)."""
        if word != "annule":
            self.type_erase_until = -1e9      # autre commande faite : « iris annule » reprend son sens habituel
        self.last_word = (word, t, True)
        self.freeze_until = -1e9              # commande reçue : le curseur est libéré après elle
        self.listen_until = -1e9
        if word in EDITOR_TABS:
            # hors mode Chrome : onglet suivant / précédent de VS Code (onglets Claude), après « iris » seulement.
            # L'appli vérifie que VS Code est devant avant d'envoyer la touche.
            acts.append(("editor_tab", EDITOR_TABS[word]))
            self.last_gesture = ("ONGLET " + ("SUIVANT" if word == "suivant" else "PRECEDENT") + " (VS Code)", t)
            self._arm_repeat(word, t, [("editor_tab", EDITOR_TABS[word])])
            return acts
        if word in CHROME_KEYS and word != "ferme" and word not in VOICE_HOTKEYS and word not in SIMPLE_ACTIONS:
            # hors mode Chrome : « ferme » garde son sens habituel, « agrandis / réduis » gèrent la fenêtre
            self.last_word = (word, t, False)
            self.last_gesture = (f"{word.upper()} : seulement en mode Chrome", t)
            return acts
        if word != "scroll" and self.scrolling(t):
            self._end_scroll(t)               # toute autre commande sort du défilement d'abord
        label = VOICE_LABELS.get(word, word.upper())
        if word in SIMPLE_ACTIONS:
            action, simple_label = SIMPLE_ACTIONS[word]
            acts.append(action)
            label = simple_label or label
        elif word in VOICE_HOTKEYS:
            acts.append(("hotkey", VOICE_HOTKEYS[word]))
            self._arm_repeat(word, t, [("hotkey", VOICE_HOTKEYS[word])], label)
        elif word in COMMANDS:
            label = getattr(self, "_cmd_" + COMMANDS[word])(word, t, acts) or label
        self.last_gesture = (label, t)
        return acts

    def _arm_repeat(self, word, t, acts, label=None):
        """Une commande répétable : redite seule (sans « iris ») pendant repeat_s, mêmes actions."""
        if word not in REPEATABLE:
            return
        self.repeat_until = t + self.cfg.repeat_s
        self.repeat_acts = {word: (list(acts), (label or self.last_gesture[0], t))}
        for w in REPEATABLE:              # skip puis back, efface puis undo… : comme avant, d'une touche à l'autre
            if w in VOICE_HOTKEYS and w not in self.repeat_acts:
                self.repeat_acts[w] = ([("hotkey", VOICE_HOTKEYS[w])], (VOICE_LABELS.get(w, w.upper()), t))

    # --- petites aides des commandes ---
    def _click(self, word, t, acts):
        acts += [("click", "right")] if word == "menu" else [("click", "left")] * (2 if word == "double" else 1)
        self.menu.close()
        self.last_click_t = t
        self.travel = 0.0

    def _quiet(self):
        """Ferme le menu et la bulle de la main (avant une dictée, une écoute, ou sur « stop »)."""
        self.menu.close()
        self.bubble = None

    def _start_open(self, kind, t, acts, label=None):
        """Écoute d'une phrase libre (Whisper) : nom d'appli, durée, message, rappel, volume…"""
        self.opening = True
        self.open_t0 = t
        self.open_kind = kind
        acts.append(("open_start",))
        return label
