"""Correctifs de l'audit du 19/11 (#48, #51…)."""
import time

import numpy as np

from motionzero import camera as cam_mod
from motionzero.app import ERROR_NOTICE, note_error, pick_toast


class FakeCap:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self):
        return (True, self.frames.pop(0)) if self.frames else (False, None)

    def release(self):
        pass


def test_delai_de_reconnexion_croissant_et_plafonne():
    d = [cam_mod.reconnect_delay(n) for n in (1, 2, 3, 4, 5, 6, 20)]
    assert d == [1, 2, 4, 8, 16, 30, 30]


def _camera(monkeypatch, frames, opens):
    monkeypatch.setattr(cam_mod, "reconnect_delay", lambda n: 0.0)
    c = cam_mod.Camera(lost_after_s=0.0)
    c.cap = FakeCap(frames)
    c.running = True
    calls = []

    def fake_open():
        calls.append(1)
        if len(calls) >= opens:
            c.running = False
        return None
    c._open = fake_open
    return c, calls


def test_camera_absente_cause_autre_appli(monkeypatch):
    c, calls = _camera(monkeypatch, [], opens=3)
    c._run()
    assert c.fails >= 2 and "autre appli" in c.problem[0]


def test_images_rejetees_cause_illisible(monkeypatch):
    noir = np.zeros((480, 640, 3), np.uint8)    # uniforme : rejetée
    c, _ = _camera(monkeypatch, [noir] * 5, opens=1)
    c._run()
    assert "illisible" in c.problem[0]


def test_bonne_image_efface_le_probleme(monkeypatch):
    rng = np.random.default_rng(0)
    img = np.clip(np.cumsum(rng.integers(-3, 4, (480, 640, 3)), axis=1) + 120, 0, 255).astype(np.uint8)
    c, _ = _camera(monkeypatch, [img], opens=1)
    c.fails, c.problem = 4, ("x", 0.0)
    c._run()
    assert c.fails == 1 and c.problem[0] != "x"   # remis à 0 par la bonne image, puis une nouvelle perte


def test_erreur_simple_puis_repetee():
    ERROR_NOTICE.update(t=[], notice=None)
    note_error("boucle")
    assert ERROR_NOTICE["notice"][0].startswith("ERREUR (boucle)")
    for _ in range(4):
        note_error("boucle")
    assert "REPETEE" in ERROR_NOTICE["notice"][0]


def test_toast_le_plus_recent_gagne():
    assert pick_toast(None, ("a", 1.0), ("b", 3.0), ("c", 2.0)) == ("b", 3.0)
    assert pick_toast(None, None) is None


def test_journal_ne_garde_que_le_debut_de_la_phrase():
    from motionzero.voice import apercu
    assert apercu("comment je pourrais soulever cent kilos") == "'comment je pourrais soulever…' (6 mots)"
    assert apercu("deux mots") == "'deux mots'"
    assert apercu(None) == "''"


def test_transcription_apres_dechargement_recharge_sous_le_verrou():
    from motionzero import ask

    class Seg:
        text = " bonjour "

    class Model:
        def transcribe(self, *a, **k):
            return [Seg()], None
    a = ask.Asker.__new__(ask.Asker)
    import threading
    a._model_lock, a._whisper, a._used_t = threading.Lock(), None, 0.0
    loads = []

    def fake_locked():
        assert a._model_lock.locked()          # jamais hors du verrou
        if a._whisper is None:
            loads.append(1)
            a._whisper = Model()
    a._load_locked = fake_locked
    assert a._transcribe(b"\x00\x00" * 160, 16000) == "bonjour"
    assert loads == [1]


def test_quota_jeton_expire_dit_quoi_faire():
    import urllib.error
    from motionzero.quota import Quota

    def refuse(token):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", None, None)
    q = Quota(token_reader=lambda: "x", fetcher=refuse)
    assert q.refresh_now() is False
    assert q.lines() == [("", "Quota : rouvre Claude Code")]
    q.fetcher = lambda tok: (_ for _ in ()).throw(OSError("reseau"))
    q.refresh_now()
    assert q.lines() == [("", "Quota indisponible")]


def test_rappel_heure_seule_et_plusieurs_rappels():
    from datetime import datetime
    from motionzero.reminders import validate, pending_text
    now = datetime(2026, 11, 19, 12, 0)
    kind, r = validate({"action": "create", "text": "", "at": "2026-11-19T17:00"}, now, set())
    assert kind == "create" and r.text == "Rappel"
    kind, rs = validate({"action": "create_many", "items": [
        {"text": "glace", "at": "2026-11-19T18:00"}, {"text": "attelle", "at": "2026-11-20T09:00"}]}, now, set())
    assert kind == "create_many" and [x.text for x in rs] == ["glace", "attelle"]
    assert pending_text(("create_many", rs), now).startswith("2 rappels")
    # un seul mauvais : tout est refusé (pas de demi-enregistrement)
    kind, why = validate({"action": "create_many", "items": [
        {"text": "a", "at": "2026-11-19T18:00"}, {"text": "b", "at": "hier"}]}, now, set())
    assert kind == "error" and "heure" in why
    assert validate({"action": "create_many", "items": []}, now, set())[0] == "error"
    assert validate({"action": "create_many", "items": [{"text": "a", "at": "2026-11-19T18:00"}]}, now, set())[0] == "create"


def test_bot_absent_dit_quoi_faire_sans_doubler_le_lancement():
    from motionzero.app import bot_absent
    from motionzero.discord_link import BotLink
    assert bot_absent(None) == "BOT DISCORD ABSENT"
    b = BotLink.__new__(BotLink)
    b.conf, b.launch_enabled, b._last_launch = {}, True, 0.0
    b.clock = lambda: 1000.0
    b.bot_dir = "C:/nulle-part"
    assert bot_absent(b) == "BOT DISCORD ABSENT"           # exécutable introuvable : pas de promesse
    b.launch_enabled = False
    assert bot_absent(b) == "BOT DISCORD ABSENT"


def test_message_discord_bot_absent_repond_tout_de_suite():
    from motionzero.app import open_actions

    class L:
        def stop_capture(self):
            return b""
    said = []
    assert open_actions([("message_stop",), ("autre",)], L(), None, asker=None, bot=None,
                        on_message=said.append) == [("autre",)]
    assert said == ["BOT DISCORD ABSENT"]


def test_agrippe_tient_jusqu_a_etre_redit():
    from motionzero.config import Config
    from motionzero.core import Core
    from motionzero.output import Controller, FakeBackend
    cfg = Config()
    ctl = Controller(FakeBackend(), cfg)
    c = Core(cfg)
    c.set_mouse(True, 1.0, [])
    ctl.execute(c.voice("agrippe", 5.0, t_start=4.8), 5.0)
    assert ("mouse", "left") in ctl.held
    ctl.execute([("release_all",)], 6.0)                    # main sortie, souris éteinte… : tient
    ctl.execute([], 5.0 + cfg.max_hold_s + 60)               # aucun délai maximal
    assert ("mouse", "left") in ctl.held and c.dragging
    ctl.execute(c.voice("agrippe", 9999.0, t_start=9998.8), 9999.0)   # redit : relâché
    assert ("mouse", "left") not in ctl.held and not c.dragging


def test_stop_et_pause_relachent_l_agrippe():
    from motionzero.config import Config
    from motionzero.core import Core
    from motionzero.output import Controller, FakeBackend
    for fin in ("stop", "pause"):
        cfg = Config()
        ctl, c = Controller(FakeBackend(), cfg), Core(cfg)
        c.set_mouse(True, 1.0, [])
        ctl.execute(c.voice("agrippe", 5.0, t_start=4.8), 5.0)
        acts = c.voice(fin, 6.0) if fin == "stop" else (c.voice("iris", 6.0) + c.voice("pause", 6.2))
        ctl.execute(acts, 6.3)
        assert ("mouse", "left") not in ctl.held and not c.dragging, fin


def test_ilot_montre_agrippe():
    from motionzero.ui import island_text
    assert "AGRIPPE" in island_text({"mode": "NEUTRE", "mouse": True, "dragging": True})[0]
    assert "AGRIPPE" not in island_text({"mode": "NEUTRE", "mouse": True})[0]
