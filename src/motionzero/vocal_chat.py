"""Bot vocal TEMPORAIRE (iris-discord-bot #1) : Iris parle dans le salon Discord avec Haiku.

Le bot ne peut pas encore écouter Discord (réception DAVE, bot #2). Donc :
- « iris parle » puis une phrase : Iris (micro du PC) transcrit, Haiku répond, le bot le dit dans le vocal ;
- un ami qui écrit « @Iris … » dans le salon : Haiku répond à voix haute aussi.
Version pour rigoler ; une vraie version (le bot entend tout le monde) viendra avec la réception DAVE.
Tout tourne dans des fils « vocal » : jamais Core ici (messages remis par on_message).
"""
import logging
import threading
from collections import deque

log = logging.getLogger(__name__)

PERSONA = ("Tu es Iris, une IA un peu insolente qui traîne dans un salon vocal Discord entre potes. "
           "Tu as de l'humour, tu taquines gentiment, tu réagis comme une amie de la bande. "
           "Tu réponds à l'oral, en français familier, en une ou deux phrases courtes. "
           "Jamais d'emoji, de liste, de markdown ni d'astérisques : ta réponse est lue à voix haute.")
HISTORY = 12                 # dernières répliques gardées pour suivre la conversation


class Chat:
    def __init__(self, ask):
        self.ask = ask                      # ask(question, system=...) -> texte (Haiku)
        self.history = deque(maxlen=HISTORY)
        self.lock = threading.Lock()

    def reply(self, author, text):
        """Réponse de Haiku à « author : text », avec le fil de la conversation. Lève en cas d'échec."""
        with self.lock:
            past = "\n".join(self.history)
            prompt = (f"Conversation récente :\n{past}\n\n" if past else "") + f"{author} : {text}\nIris :"
            answer = " ".join(str(self.ask(prompt, system=PERSONA)).split()).strip().strip('"')
            if not answer:
                raise RuntimeError("réponse vide")
            self.history.append(f"{author} : {text}")
            self.history.append(f"Iris : {answer}")
            return answer


def _ask(question, system):
    from .ask import ask_claude
    return ask_claude(question, system=system)


CHAT = Chat(_ask)
STATE = {"in_voice": False}    # le bot est-il dans un salon vocal ? (écrit par la boucle principale seulement)


def chat_turn(chat, bot, on_message, author, text):
    """Fil « vocal » : Haiku répond, le bot le dit dans le salon."""
    try:
        answer = chat.reply(author, text)
    except Exception:
        log.exception("Haiku indisponible (vocal)")
        on_message("IRIS VOCAL : HAIKU INDISPONIBLE")
        return
    log.info("vocal : %s : %s -> %s", author, text, answer)
    if bot is None or bot.send({"t": "say", "text": answer}) is None:
        on_message("BOT DISCORD ABSENT")
        return
    on_message(f"IRIS : {answer}"[:60])


def chat_spoken(audio, transcribe, chat, bot, on_message, author="le créateur d'Iris"):
    """« iris parle » : transcrit ta phrase puis lance la réponse."""
    try:
        text = (transcribe(audio) or "").strip(" .")
    except Exception:
        log.exception("transcription vocal")
        text = ""
    if not text:
        on_message("RIEN ENTENDU")
        return
    chat_turn(chat, bot, on_message, author, text)
