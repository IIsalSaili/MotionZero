"""Rejoue un enregistrement et affiche les actions qui auraient été envoyées (rien n'est envoyé).

  python tools/replay.py sortie.jsonl [config.json]
"""
import sys

from motionzero.config import load_config
from motionzero.replay import replay

cfg = load_config(sys.argv[2]) if len(sys.argv) > 2 else None
for t, action in replay(sys.argv[1], cfg):
    print(f"{t:8.3f} s  {action}")
