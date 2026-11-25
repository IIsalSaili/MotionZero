"""Traitement des actions du moteur : question, ouvre / ferme, Discord, dictée, VS Code et Chrome (découpé de app.py, #52)."""
import logging
import queue
import threading
import time


from .vscode import chrome_in_front, chrome_tab_count
from . import pont

from .app_outils import last_tab

_log = logging.getLogger("motionzero")


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


def bot_absent(bot):
    """Message quand le bot ne répond pas : on relance tout de suite s'il peut l'être (#57)."""
    if bot is not None and getattr(bot, "enabled", False) and bot.launch_now():
        return "BOT DISCORD ABSENT : il demarre, redis dans 30 s"
    return "BOT DISCORD ABSENT"


def open_actions(acts, listener, launcher, asker=None, bot=None, on_message=None, desk=None, instructeur=None,
                 candidature=None):
    """« iris ouvre / message / salon » : ce qui suit est enregistré, transcrit, puis traité."""
    rest = []
    for a in acts:
        if a[0] == "open_start":
            listener.start_capture()
        elif a[0] == "timer_stop":
            audio = listener.stop_capture()
            if desk is not None:
                desk.submit_timer(audio)
        elif a[0] == "volume_show":
            from .volume import volume_peek
            threading.Thread(target=volume_peek, name="volume", daemon=True).start()
        elif a[0] in ("bot_join", "bot_leave"):
            order = {"bot_join": "join", "bot_leave": "leave"}[a[0]]
            if bot is None or bot.send({"t": order}) is None:
                on_message(bot_absent(bot))
        elif a[0] == "volume_stop":
            from .volume import volume_spoken
            audio = listener.stop_capture()
            threading.Thread(target=volume_spoken, args=(audio, lambda au: asker._transcribe(au, 16000), on_message),
                             name="volume", daemon=True).start()
        elif a[0] == "rappel_stop":
            audio = listener.stop_capture()
            if desk is not None:
                desk.submit(audio)
        elif a[0] == "instruction_warm":
            if instructeur is not None:
                instructeur.warm()
        elif a[0] == "instruction_stop":
            audio = listener.stop_capture()
            if instructeur is not None:
                instructeur.submit(audio)
        elif a[0] in ("message_stop", "salon_stop"):
            audio = listener.stop_capture()
            if bot is None or not bot.connected:   # #57 : dit tout de suite, sans attendre la transcription
                on_message(bot_absent(bot))
                continue
            threading.Thread(target=discord_spoken, args=(a[0], audio, asker, bot, on_message),
                             name="discord", daemon=True).start()
        elif a[0] == "candq_stop":               # #46 : question libre du formulaire
            audio = listener.stop_capture()
            if candidature is not None and asker is not None:
                candidature.submit_question(audio, lambda au: asker._transcribe(au, 16000))
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
        on_message(bot_absent(bot))
        return
    msg = {"t": "send", "text": text} if kind == "message_stop" else {"t": "move", "channel": text}
    if bot.send(msg) is None:
        on_message("BOT DISCORD OCCUPE")


def bot_events(bot, core, speaker, discord_voice, t, listener=None):
    """Ce que le bot a envoyé (fil « pont-bot ») : traité ici, dans la boucle principale. Renvoie les actions
    des commandes écrites en MP (#43)."""
    from .discord_link import result_label, speech_for
    acts = []
    for p in list(bot.pending_cmds):          # commandes par MP : réponse quand l'effet se voit dans l'île
        reply = p.reply(core.last_gesture, t)
        if reply is not None:
            bot.pending_cmds.remove(p)
            bot.send(reply)
    while True:
        try:
            msg = bot.inbox.get_nowait()
        except queue.Empty:
            return acts
        kind = msg.get("t")
        if kind == "command":
            acts += discord_command(bot, core, msg, t, listener)
        elif kind == "result" and bot.kinds.get(msg.get("req")) == "command_result":
            bot.kinds.pop(msg.get("req"), None)  # réponse au MP transmise : rien à afficher
        elif kind == "message":
            core.last_gesture = (f"{msg.get('author', '?')} : {msg.get('content', '')}"[:60], t)
            if speaker is not None:
                speaker.say(speech_for(msg))
        elif kind == "voice_state":
            # état réel vu par Discord (#6) : remplace la simple mémoire des raccourcis.
            # Hors vocal, Discord ne dit rien du micro (None) : la mémoire reste telle quelle.
            if msg.get("channel") is not None and msg.get("self_mute") is not None:
                discord_voice["mute"] = bool(msg["self_mute"])
                discord_voice["deaf"] = bool(msg.get("self_deaf"))
        elif kind == "result" and bot.kinds.get(msg.get("req")) in ("join", "leave", "activate", "send", "move"):
            core.last_gesture = (result_label(msg, bot.kinds.pop(msg.get("req"))), t)
            from .discord_cmd import BOT_WORDS
            for p in bot.pending_cmds:        # une commande par MP attendait cette réponse du bot
                if p.word in BOT_WORDS and p.bot_result is None:
                    p.bot_result = (bool(msg.get("ok")), core.last_gesture[0])
                    break
        elif kind == "result" and bot.kinds.get(msg.get("req")) == "notify":
            bot.kinds.pop(msg.get("req"), None)          # rappel envoyé en privé : rien à afficher
            if not msg.get("ok"):
                logging.getLogger("motionzero").warning("rappel non envoye sur Discord : %s", msg.get("error"))
        elif kind == "result":
            core.last_gesture = (result_label(msg, bot.kinds.pop(msg.get("req"), "send")), t)
        elif kind == "link" and not msg.get("connected") and bot.was_connected:
            core.last_gesture = ("BOT DISCORD DECONNECTE", t)


def discord_command(bot, core, msg, t, listener=None):
    """Commande écrite en MP au bot : comme « iris » + le mot dit. Une phrase qui suit (« ouvre spotify ») remplace
    l'enregistrement du micro : la capture est finie tout de suite, comme après un silence. L'écoute retrouve
    son état d'avant (une commande à distance ne doit pas laisser le micro ouvert aux conversations de la pièce)."""
    from .discord_cmd import BOT_WORDS, WAIT_BOT_S, WAIT_PHRASE_S, WAIT_S, Pending, error_reply, parse
    word, phrase, err = parse(msg.get("text"))
    _log.info("commande par MP : %r -> %s", msg.get("text"), word or err[0])
    if not err and phrase and listener is None:
        err = ("pas_de_micro", [])
    if err:
        bot.send(error_reply(msg.get("id"), *err))
        return []
    before, listen_until = core.last_gesture, core.listen_until
    try:
        acts = []
        if word == "claude" and phrase:       # le micro de Claude ne prend pas de texte : VS Code devant, puis tapé
            acts += core.voice("iris", t) + core.voice("studio", t)
            word = "type"
        if phrase:
            listener.typed = phrase
        acts += core.voice("iris", t) + core.voice(word, t)
        if phrase:
            far = t + 1000.0                  # « parlé » puis silence : chaque écoute se coupe comme d'habitude
            stops = core.open_tick(far, t + 500.0) + core.ask_tick(far, t + 500.0) + core.type_tick(far, t + 500.0)
            acts += stops
            if not stops:                     # aucune écoute ouverte (ex. « timer » qui annule) : texte inutilisé
                listener.typed = None
            if core.last_gesture and core.last_gesture[1] == far:
                core.last_gesture = (core.last_gesture[0], t)
    except Exception:
        _log.exception("commande par MP %s", word)
        if listener is not None:
            listener.typed = None
        bot.send({"t": "command_result", "id": msg.get("id"), "ok": False,
                  "text": "Erreur dans Iris pendant la commande (voir les journaux)."})
        return []
    if word != "reprise" and core.listen_until > listen_until:
        core.listen_until = listen_until
    if core.last_word and not core.last_word[2]:
        if listener is not None:
            listener.typed = None
        bot.send({"t": "command_result", "id": msg.get("id"), "ok": False,
                  "text": f"Ignorée : {(core.last_gesture or ('?',))[0]}"})
        return acts
    wait = WAIT_BOT_S if word in BOT_WORDS else WAIT_PHRASE_S if phrase else WAIT_S
    bot.pending_cmds.append(Pending(msg.get("id"), word, before, t, wait))
    return acts


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
    from .vscode import (alt_tab_to, discord_mute_toggle, find_window, focus_and_send, open_app,
                         toggle_claude_dictation, vscode_in_front, foreground_exe, IRIS_EXES)

    def send(keys):
        ctl.execute([("hotkey", keys)], time.perf_counter())

    rest = []
    for a in acts:
        if a[0] == "chrome_keys":
            if chrome_in_front():
                if a[1] == ["ctrl", "w"] and last_tab(chrome_tab_count()):
                    core.last_gesture = ("DERNIER ONGLET : Chrome reste ouvert", t)
                    _log.info("ferme ignore : dernier onglet de Chrome")
                    continue
                rest.append(("hotkey", a[1]))
            else:
                core.last_gesture = ("CHROME PAS DEVANT : rien envoye", t)
            continue
        if a[0] == "editor_tab":
            # d'abord le pont (extension) : commande de VS Code, effet vérifié ; sinon l'ancienne touche
            sens = "next" if "pagedown" in a[1] else "prev"
            res = pont.command(sens)
            if res is not None:
                ok, info = res
                if ok:
                    core.last_gesture = ("ONGLET " + ("SUIVANT" if sens == "next" else "PRECEDENT")
                                         + (f" : {info[:30]}" if info else ""), t)
                else:
                    _log.info("onglet VS Code pas change : %s", info)
                    core.last_gesture = (f"ONGLET : ECHEC ({info})".upper(), t)   # « ECHEC » : son d'échec
                continue
            if vscode_in_front():
                rest.append(("hotkey", a[1]))
                continue
            devant = foreground_exe()
            if devant in IRIS_EXES and find_window() is not None:
                # une fenêtre d'Iris (aide, accueil…) a pris le premier plan : VS Code reste la cible
                err = focus_and_send(send, [a[1]])
                if err:
                    core.last_gesture = (err, t)
            else:
                _log.info("onglet VS Code refuse : premier plan = %s", devant or "aucun")
                core.last_gesture = ("VS CODE PAS DEVANT : rien envoye", t)
            continue
        if a[0] == "annule":
            if vscode_in_front():
                err = focus_and_send(send, [["ctrl", "a"], ["backspace"]])   # vide le message de Claude
            else:
                rest.append(("hotkey", ["escape"]))                         # ailleurs : touche Échap
                continue
        elif a[0] == "alt_tab":
            from .alttab import list_text
            try:
                ok, err, titles = alt_tab_to(a[1])
            except Exception:                  # une fenêtre fermée entre-temps, une erreur Windows : Iris continue
                _log.exception("alt-tab")
                ok, err, titles = False, "ALT-TAB : ECHEC", []
            core.alttab_text = list_text(titles)
            if not core.alttab_text:
                core.alttab_until = -1e9       # aucune autre fenêtre : rien à afficher, chiffres plus écoutés
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
            from .vscode import claude_mic_state
            real = claude_mic_state()
            if real is not None and real == core.dictating:
                # déjà dans l'état voulu (Claude a coupé son micro seul, ou il était déjà allumé) : la
                # bascule ferait l'inverse
                _log.info("micro Claude deja %s : raccourci non envoye", "allume" if real else "coupe")
                err = None
            else:
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


