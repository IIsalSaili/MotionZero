"""Commandes « iris + mot » (table COMMANDS). Méthodes de Core (découpé de core.py, #52) : seulement boucle principale."""
import math

from .core_mots import (ALIASES, BYPASS_IDLE_S, CAL_IDLE_S, CAL_WORDS, CAND_IDLE_S, CHROME_GRACE_S, CHROME_KEYS, CHROME_LABELS, COMMANDS, EDITOR_TABS, FOCUS_IDLE_S, HELP_S, IRIS_EXES, MENU_LABELS, Mode, OPEN_STOP, OPEN_WAIT, REPEATABLE, SIMPLE_ACTIONS, TYPE_ERASE_S, TYPE_WAIT_S, VOICE_HOTKEYS, VOICE_LABELS, WAKE_WORD, head_gain)  # noqa: F401


class CommandesMixin:

    # --- commandes « iris + mot » (table COMMANDS) : ajoutent leurs actions, renvoient un libellé ou None ---
    def _cmd_click(self, word, t, acts):
        self._aim(self.wake_t, acts)          # là où l'on visait en disant « iris »
        self._click(word, t, acts)

    def _cmd_grip(self, word, t, acts):
        """« agrippe » : enfonce le bouton gauche (glisser) ; redit, il est relâché (voir _v_stop)."""
        self._aim(self.wake_t, acts)
        acts.append(("press", "mouse", "left", "sticky"))   # tenu jusqu'à « agrippe » redit (ni délai ni main)
        self.dragging = True

    def _cmd_scroll(self, word, t, acts):
        if self.scrolling(t):                 # « iris défile » une 2e fois : on en sort
            self._end_scroll(t)
            return "DEFILEMENT FINI"
        self.voice_scroll_until = math.inf    # actif jusqu'à « iris défile », « stop » ou une autre commande
        self.voice_scroll_armed = False
        self.voice_scroll_since = None
        self._scroll_acc = 0.0
        self._quiet()
        return "DEFILE : amene la main au centre"

    def _cmd_claude(self, word, t, acts):
        self.dictating = True
        self.dictation_t0 = t
        self._quiet()
        acts.append(("vscode_dictation",))

    def _cmd_mouse(self, word, t, acts):
        # allume ou éteint la souris ; le mode en cours (Chrome…) ne change pas
        self.set_mouse(not self.mouse, t, acts)
        return "SOURIS" if self.mouse else "SOURIS ETEINTE"

    def _cmd_question(self, word, t, acts):
        self.asking = True
        self.ask_t0 = t
        acts.append(("ask_start",))
        return "POSE TA QUESTION"

    def _cmd_open(self, word, t, acts):
        return self._start_open("open", t, acts, "OUVRE : dis le nom de l'appli")

    def _cmd_type(self, word, t, acts):
        self.typing = True
        self.type_t0 = t
        self._quiet()
        acts.append(("type_start",))

    def _cmd_close(self, word, t, acts):
        # retire la réponse affichée ET écoute un éventuel nom d'appli à fermer (en mode Chrome, « ferme »
        # ferme l'onglet : pour l'affichage du haut, « merci » / « ok » marchent partout)
        acts.append(("ask_close",))
        return self._start_open("close", t, acts, "FERME : dis le nom de l'appli")

    def _cmd_timer(self, word, t, acts):
        if self.timer_running:
            acts.append(("timer_cancel",))
            return "TIMER ANNULE"
        return self._start_open("timer", t, acts, "TIMER : combien de temps ?")

    def _cmd_help(self, word, t, acts):
        # redit pendant qu'elle est affichée : fermée
        self.help_until = -1e9 if t < self.help_until else t + HELP_S
        return "AIDE" if self.help_until > t else "AIDE FERMEE"

    def _cmd_guide(self, word, t, acts):
        acts.append(("guide",))
        return "GUIDE : ouvert dans le navigateur"

    def _cmd_calendar(self, word, t, acts):
        self.calendar_until = t + CAL_IDLE_S
        acts.append(("cal_open",))

    def _cmd_clock(self, word, t, acts):
        self.clock_until = t + self.cfg.clock_s

    def _cmd_focus(self, word, t, acts):
        """« iris focus » : commandes sans « iris » ; « focus » (seul) l'éteint ; seul après 10 min sans commande."""
        if self.focus_on(t):
            self.focus_until = -1e9
            return "FOCUS ETEINT : redis IRIS avant"
        self.focus_until = t + FOCUS_IDLE_S
        return "FOCUS : plus besoin de dire IRIS"

    def _cmd_translator(self, word, t, acts):
        """« iris traducteur » : allume les sous-titres traduits ; redit, les éteint."""
        self.translating = not self.translating
        acts.append(("traducteur", self.translating))
        return "TRADUCTEUR ALLUME" if self.translating else "TRADUCTEUR ETEINT"

    def bypass_on(self, t):
        return self.mode != Mode.DISABLED and t < self.bypass_until

    def _cmd_bypass(self, word, t, acts):
        """« iris bypass » : reconnaissance plus permissive (voir voice.BYPASS_*) ; redit, éteint ; seul après
        10 min sans commande. S'ajoute au mode focus sans le changer."""
        if self.bypass_on(t):
            self.bypass_until = -1e9
            return "BYPASS ETEINT"
        self.bypass_until = t + BYPASS_IDLE_S
        return "BYPASS : mots acceptes meme mal dits"

    def _cmd_quota(self, word, t, acts):
        self.quota_shown = not self.quota_shown
        acts.append(("quota", self.quota_shown))
        return "QUOTA AFFICHE" if self.quota_shown else "QUOTA MASQUE"

    def _cmd_thanks(self, word, t, acts):
        # « vu » : tout ce qui est affiché en haut disparaît (rappel validé, réponse, liste, heure)
        acts += [("rappel_merci",), ("ask_close",)]
        self.clock_until = -1e9

    def _cmd_listen(self, word, t, acts):
        # message, salon, rappel, volume : la suite est une phrase libre (« iris volume » puis « 40 »…)
        self._quiet()
        self._start_open(word, t, acts)
        if word == "volume":
            acts.append(("volume_show",))     # barre de volume à droite, avec le niveau actuel

    def _cmd_pointer(self, word, t, acts):
        self.set_pointer("tete" if word == "tête" else "main", t, acts)
        return "SOURIS A LA " + ("TETE" if word == "tête" else "MAIN")

    def _cmd_center(self, word, t, acts):
        self.head.reset()                     # tête de face maintenant = centre
        if self.mouse:
            self._center(acts)
        return "CURSEUR AU CENTRE"

    def _cmd_reading(self, word, t, acts):
        self.set_mouse(False, t, acts)        # la main sert aux pages, plus au curseur
        if self.mode != Mode.READING:
            self.set_mode(Mode.READING, t, acts, why="iris lecture")
        return "LECTURE"

    def _cmd_app(self, word, t, acts):
        acts.append(("open_app", word))
        if word == "chrome" and self.mode in (Mode.NEUTRAL, Mode.CHROME):
            self.set_mode(Mode.CHROME, t, acts, why="iris chrome")
        # discord / studio : le mode Chrome s'arrête quand leur fenêtre passe devant (front_app) ;
        # accueil (fenêtre d'Iris) ne le fait plus quitter

    def _cmd_pause(self, word, t, acts):
        self.dragging = False
        acts.append(("release_all", "force"))
        self.set_mode(Mode.DISABLED, t, acts, why="pause")
        self.listen_until = -1e9
        if t < self.calendar_until:           # rien ne reste ouvert pendant la pause
            acts.append(("cal_close",))
        if self.cand_until > t:
            acts.append(("cand_off",))
        self.calendar_until = self.help_until = self.cand_until = -1e9
        return "PAUSE (dis IRIS REPRISE pour reprendre)"
