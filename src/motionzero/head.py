"""Souris à la tête : l'orientation du visage (MediaPipe Face Landmarker) devient un point « comme une paume ».

On mesure où se trouve le bout du nez par rapport au visage (et non dans l'image) : tourner la tête bouge le
curseur, se décaler sur sa chaise ne le bouge pas. Le point repart du centre (0,5 ; 0,5) au moment où la tête
est prise pour référence (souris allumée, « iris centre »), puis passe par le même pavé tactile que la main.
Pur : testable sans caméra.
"""
NOSE, LEFT, RIGHT, TOP, BOTTOM = 1, 234, 454, 10, 152   # bout du nez, joues, front, menton (maillage 478 points)


def head_offsets(lms):
    """(gauche/droite, haut/bas) du nez par rapport au centre du visage, en fraction de la taille du visage.
    lms : liste de points (x, y) normalisés. None si le visage est trop petit ou incomplet."""
    try:
        nose, left, right, top, bottom = lms[NOSE], lms[LEFT], lms[RIGHT], lms[TOP], lms[BOTTOM]
    except (IndexError, TypeError):
        return None
    width, height = abs(right[0] - left[0]), abs(bottom[1] - top[1])
    if width < 0.03 or height < 0.03:
        return None
    return ((nose[0] - (left[0] + right[0]) / 2) / width,
            (nose[1] - (top[1] + bottom[1]) / 2) / height)


class HeadPointer:
    """Point virtuel 0..1 piloté par la tête ; la référence est prise au premier visage vu après reset()."""

    def __init__(self, scale=1.5):
        self.scale = scale
        self.base = None

    def reset(self):
        self.base = None

    def point(self, lms):
        off = head_offsets(lms)
        if off is None:
            return None
        if self.base is None:
            self.base = off                  # tête de face maintenant = centre de l'écran
        x = 0.5 + self.scale * (off[0] - self.base[0])
        y = 0.5 + self.scale * (off[1] - self.base[1])
        return (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))
