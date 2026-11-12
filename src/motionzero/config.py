"""Réglages. Tout est modifiable via config.json (mêmes noms de clés)."""
import json
import os
from dataclasses import asdict, dataclass, fields


@dataclass
class Config:
    # caméra
    camera_index: int = 0
    width: int = 640
    height: int = 480

    # reconnaissance des poses (distances normalisées par la taille de la main)
    finger_ext_ratio: float = 1.1      # doigt tendu si bout-poignet > articulation-poignet * ratio
    thumb_ext_dist: float = 0.56       # pouce sorti si bout du pouce - base de l'index > seuil (0,45 avant correction largeur/hauteur, +25 % mesuré)
    thumb_up_margin: float = 0.2       # pouce levé : bout du pouce au-dessus de la base de l'index
    pose_tolerance_s: float = 0.15     # micro-coupures de pose ignorées (tremblements)

    # changements de mode
    hold_open_s: float = 0.8           # paume ouverte -> lecture
    hold_point_s: float = 0.6          # index pointé -> souris
    hold_fist_s: float = 1.0           # poing -> repos
    transition_cooldown_s: float = 0.8
    absent_reading_s: float = 60.0     # main absente -> repos (lecture) : pas besoin de réarmer à chaque page
    absent_mouse_s: float = 0.0        # 0 = la main absente ne fait plus sortir du mode souris (« iris stop »)
    release_absent_s: float = 0.5      # main absente -> on relâche tout

    # balayage (mode lecture), en fraction de largeur d'image
    swipe_window_s: float = 0.4
    swipe_min_dx: float = 0.18
    swipe_min_speed: float = 0.6
    swipe_max_dy_ratio: float = 0.6
    swipe_still_speed: float = 0.15
    swipe_still_s: float = 0.3
    swipe_cooldown_s: float = 0.7
    key_next: str = "right"
    key_prev: str = "left"

    # souris
    active_rect: tuple = (0.2, 0.2, 0.8, 0.75)   # zone de l'image étirée sur tout l'écran
    euro_min_cutoff: float = 1.0
    euro_beta: float = 0.01
    deadzone_px: float = 4.0

    # pincement
    pinch_on: float = 0.25
    pinch_off: float = 0.45            # mesuré : main ouverte ~0,72, pincée ~0,06
    pinch_release_rise: float = 0.30   # ou remontée nette au-dessus du minimum
    pinch_confirm_frames: int = 2
    pinch_click_max_s: float = 2.0     # pincement lent et tenu (~1,3 s mesuré). Le poing annule le clic.
    pinch_freeze_back_s: float = 0.15  # clic à la position d'avant le pincement
    right_click_enabled: bool = True
    right_click_margin: float = 0.08

    # clic par survol prolongé
    dwell_enabled: bool = True
    dwell_s: float = 1.0
    dwell_radius_px: float = 25.0

    # ===== Gestes v2 : aucune pose de doigts, aucun pincement (coordonnées normalisées de l'image) =====
    # pages : amener la paume au bord de l'image (bord droit = suivante)
    page_band_right: float = 0.80
    page_band_left: float = 0.20
    page_hold_s: float = 0.35
    page_rearm_lo: float = 0.30          # revenir au centre pour réarmer
    page_rearm_hi: float = 0.70
    page_refractory_s: float = 1.0

    # défilement (lecture) : paume en haut / en bas de l'image
    scroll_band_top: float = 0.12        # zones de défilement étroites (0,25 jugé beaucoup trop large)
    scroll_band_bottom: float = 0.88
    scroll_hold_s: float = 0.3           # avant de commencer à défiler
    scroll_interval_s: float = 0.15      # un cran toutes les 0,15 s tant que la main y reste
    scroll_notch: int = 120              # un cran de molette Windows

    # immobilité (à calibrer sur la main posée de l'utilisateur)
    still_window_s: float = 0.5
    still_radius: float = 0.012

    # entrer en souris : main immobile, bulle « SOURIS ? », petit mouvement vers le haut pour confirmer
    mouse_enter_still_s: float = 1.5
    bubble_confirm_dist: float = 0.05
    bubble_cancel_dist: float = 0.08
    bubble_timeout_s: float = 2.0

    # curseur relatif (type pavé tactile), gain selon la vitesse de la main
    # x2 le 12/11 (demande de l'utilisateur : le moins de mouvements possible, pas la précision)
    gain_min: float = 2.0                # mouvements lents (viser) ; avant 1,0 (1,5 jugé trop réactif à l'époque)
    gain_max: float = 7.0                # mouvements rapides ; avant 3,5
    # souris à la tête (12/11) : « main » ou « tete » ; ampleur du point virtuel par rapport au visage
    pointer: str = "main"
    # orientation de la tête (12/11) : point virtuel par radian de rotation ; ~20° couvrent la moitié de l'écran
    head_scale: float = 1.4
    head_scale_y: float = 2.0          # on lève / baisse la tête moins loin qu'on ne la tourne
    # vitesse propre à la tête : lente pour viser (petits gestes), rapide pour traverser l'écran
    head_gain_min: float = 0.8
    head_gain_max: float = 7.0
    gain_speed_lo: float = 0.05          # vitesse (largeur d'image / s) en dessous : gain_min
    gain_speed_hi: float = 0.8           # au-dessus : gain_max
    palm_min_cutoff: float = 1.5         # filtre One Euro sur la paume
    palm_beta: float = 5.0

    # clic : main immobile -> menu à 4 directions (gauche, droit, double, retour lecture)
    dwell_menu_s: float = 0.8
    start_mode: str = "NEUTRE"         # au démarrage : neutre (la main ne fait rien). « iris lecture » / « iris souris »
    mouse_bubble: bool = False         # bulle « SOURIS ? » sur main immobile ; remplacée par « iris souris »
    click_menu_on_still: bool = False  # main immobile -> menu de clic. Désactivé : réfléchir ne doit rien ouvrir
    arm_center: tuple = (0.5, 0.5)     # souris : le curseur ne bouge qu'une fois la paume amenée ici (image)
    arm_radius: float = 0.08           # tolérance autour de ce centre (largeur d'image)
    arm_hold_s: float = 0.15           # temps passé dans la zone avant d'armer (évite un passage)
    recenter_absent_s: float = 0.5     # souris : main absente au moins 0,5 s puis revenue -> curseur au centre
    index_click_recovery_s: float = 0.8 # deux clics par l'index : au moins 0,8 s d'écart
    hand_click_enabled: bool = False   # clic en rouvrant la main : désactivé (fatigant, peu fiable) ; clic à la voix, pédale plus tard
    click_pose: str = "open"           # pose qui clique : ouvrir la main détendue (après main fermée)
    hold_after_s: float = 2.0          # main gardée ouverte plus de 2 s après le clic : bouton maintenu
    index_click_frames: int = 3        # 3 images de suite dans cette pose (~0,15 s), sans bouger le curseur
    menu_neutral: float = 0.03
    menu_select: float = 0.06
    menu_timeout_s: float = 1.5
    rearm_px: float = 80.0               # bouger le curseur avant un nouveau menu
    click_recovery_s: float = 0.5

    # voix : « iris » (ou bulle / menu affichés) ouvre l'écoute
    listen_s: float = 3.5                # écoute après « iris » dit seul ; une seule commande, puis fermée
    voice_scroll_s: float = 8.0          # « défile » : la hauteur de la main règle le défilement
    voice_scroll_dead: float = 0.04      # zone neutre autour de la hauteur de départ
    voice_scroll_max_rate: float = 15.0  # crans par seconde au maximum

    # « iris, claude » : micro du panneau Claude dans VS Code, coupé quand tu as fini de parler
    dictation_silence_s: float = 2.75    # silence après ta dernière parole -> micro coupé (2 s trop court, 4 s trop long)
    dictation_echo_s: float = 0.6        # on ignore la fin de « claude » juste après l'avoir dit
    dictation_no_speech_s: float = 8.0   # rien dit du tout -> micro coupé
    type_silence_s: float = 2.0          # « iris type » : silence qui coupe l'écoute (plus court que pour Claude)
    open_silence_s: float = 1.2          # « iris ouvre » : silence après le nom de l'appli
    open_no_speech_s: float = 5.0        # « iris ouvre » sans nom : abandon
    clock_s: float = 5.0                 # « iris heure / date » : durée d'affichage (animation comprise)
    repeat_s: float = 2.0                # après « iris skip / back » : « skip » / « back » seuls marchent pendant 2 s
    close_no_speech_s: float = 2.5       # « iris ferme » sans nom : seulement la réponse retirée
    type_confirm_s: float = 3.0          # « iris type » : temps pour dire « envoie » / « annule » (sinon : rien)
    send_confirm_s: float = 30.0         # temps pour dire « envoie » / « annule »

    # sécurité et confort
    max_hold_s: float = 10.0           # sécurité : tout appui maintenu est relâché après 10 s (glisser compris)
    sounds: bool = True
    sound_volume: float = 0.5          # volume des sons d'Iris (0 à 1) ; 1 jugé trop fort (12/11)


def load_config(path=None) -> Config:
    cfg = Config()
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return cfg  # fichier illisible : valeurs par défaut
        known = {f.name for f in fields(Config)}
        for key, value in data.items():
            if key in known:
                setattr(cfg, key, tuple(value) if isinstance(value, list) else value)
    return cfg


def save_config(cfg: Config, path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(cfg), fh, indent=2, ensure_ascii=False)
