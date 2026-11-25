"""Outils supplémentaires d'« iris instruction » (#45) : routines, favoris, vidéo, onglets, historique, infos,
fenêtres, musique. Aucun ne modifie de fichier de l'utilisateur, n'éteint l'ordinateur ni ne change un réglage :
les seuls fichiers écrits sont ceux d'Iris (routines.json, favoris.json, non versionnés).
Les fonctions pures (calcul, conversions, choix dans l'historique…) sont testables sans Windows.
"""
import logging
from .outils_base import (CITY_TZ, MEDIA_VK, SEARCH, Store, UNITS, VIDEO, WMO, _OPS, _get_json, calc, chrome_history_files, convert, find_tab, fmt_num, from_history, front, front_title, media_vk, norm_name, pick_history, read_history, search_url, send_keys, send_vk, snap, split_pair, time_in, video_keys)  # noqa: F401
from .outils_base2 import (CURRENCIES, EXAMPLES, SITES, _ddg, find_site, known_site, money, weather)  # noqa: F401

log = logging.getLogger("motionzero.outils")
