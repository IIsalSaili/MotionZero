"""Souris à la tête : la position du bout du nez dans l'image (MediaPipe Face Landmarker) devient un point
« comme une paume ».

Demande de l'utilisateur (12/11) : la position du nez dans l'image tout court (comme la paume en mode main),
et non le nez comparé au reste du visage : bouger la tête, ou le buste, bouge le curseur. Le point repart du
centre (0,5 ; 0,5) au moment où la tête est prise pour référence (souris allumée, « iris centre »), puis passe
par le même pavé tactile que la main. Pur : testable sans caméra.
"""
NOSE = 1                   # bout du nez (maillage de 478 points)

HEAD_MIN_CUTOFF = 0.4      # lissage fort tête immobile (le maillage du visage tremble d'une image à l'autre)
HEAD_BETA = 20.0           # ... mais réactif quand la tête bouge vraiment (unités : fraction de l'image)
HEAD_DEADZONE = 0.0016     # variation plus petite (fraction de l'image) : ignorée


def nose_position(lms):
    """(x, y) du bout du nez dans l'image (0..1), ou None si pas de visage."""
    try:
        x, y = lms[NOSE][0], lms[NOSE][1]
    except (IndexError, TypeError):
        return None
    return (x, y)


class HeadPointer:
    """Point virtuel 0..1 piloté par le nez ; la référence est prise au premier visage vu après reset().
    Mesuré le 12/11 : sans lissage propre, le curseur tremblait tête immobile (bruit du maillage amplifié
    par l'ampleur et la vitesse de la souris)."""

    def __init__(self, scale=7.5, scale_y=None):
        from .filters import OneEuro
        self.scale = scale
        self.scale_y = scale if scale_y is None else scale_y
        self.base = None
        self.fx = OneEuro(HEAD_MIN_CUTOFF, HEAD_BETA)
        self.fy = OneEuro(HEAD_MIN_CUTOFF, HEAD_BETA)
        self.held = None

    def reset(self):
        self.base = None
        self.held = None
        self.fx.reset()
        self.fy.reset()

    def point(self, lms, t=None):
        raw = nose_position(lms)
        if raw is None:
            return None
        if t is not None:
            raw = (self.fx(raw[0], t), self.fy(raw[1], t))
        if self.held is not None and max(abs(raw[0] - self.held[0]), abs(raw[1] - self.held[1])) < HEAD_DEADZONE:
            raw = self.held                  # micro-variation : on ne bouge pas
        self.held = raw
        if self.base is None:
            self.base = raw                  # position de la tête maintenant = centre de l'écran
        x = 0.5 + self.scale * (raw[0] - self.base[0])
        y = 0.5 + self.scale_y * (raw[1] - self.base[1])
        return (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))
