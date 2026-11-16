import pytest


@pytest.fixture(autouse=True)
def _pont_coupe(monkeypatch):
    """Les tests ne parlent jamais au vrai VS Code : pont injoignable, sauf test qui le remplace."""
    import motionzero.pont as pont
    monkeypatch.setattr(pont, "command", lambda name: None)
