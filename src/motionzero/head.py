"""Souris à la tête : l'ORIENTATION de la tête (gauche/droite, haut/bas) devient un point « comme une paume ».

Choix du 12/11 après essais : le nez seul dans l'image tremblait et bougeait avec le buste ; le nez comparé au
visage marchait mieux (c'était déjà une mesure de rotation, mais sur 5 points). L'orientation calculée par
MediaPipe sur tout le visage (478 points, matrice de transformation) est la plus stable : le tremblement des
points se compense, seules les rotations comptent.

Le sens des axes de la matrice n'a pas pu être vérifié sans visage réel : il est confirmé (et corrigé si besoin)
pendant les premiers mouvements en le comparant au nez rapporté au visage, dont le sens est sûr.
Sans matrice, on se rabat sur ce nez rapporté au visage (groupes de points moyennés). Pur : testable sans caméra.
"""
import math

# groupes de points (maillage de 478) : moyennés pour réduire le tremblement de chacun
NOSE_PTS = (1, 4, 5, 195, 197)               # pointe et arête du nez
LEFT_PTS = (234, 93, 132)                    # bord gauche du visage (dans l'image)
RIGHT_PTS = (454, 323, 361)
TOP_PTS = (10, 109, 338)                     # front
BOTTOM_PTS = (152, 148, 377)                 # menton

POSE_MIN_CUTOFF = 0.6      # lissage fort tête immobile...
POSE_BETA = 0.5            # ... réactif quand elle tourne (unités : radians)
POSE_DEADZONE = 0.003      # ~0,2 degré : variation ignorée (l'orientation tremble beaucoup moins qu'un point)
SIGN_VOTES = 3             # mouvements nets concordants avant de corriger le sens d'un axe
REL_MOVE, POSE_MOVE = 0.06, 0.04             # « mouvement net » : nez/visage et radians


def _mean(lms, idx):
    return (sum(lms[i][0] for i in idx) / len(idx), sum(lms[i][1] for i in idx) / len(idx))


def head_offsets(lms):
    """Nez par rapport au visage (fraction de la taille du visage), groupes de points moyennés. Sens sûr :
    x croît quand le nez va vers la droite de l'image, y quand il descend. None si visage absent ou minuscule."""
    try:
        nose, left, right = _mean(lms, NOSE_PTS), _mean(lms, LEFT_PTS), _mean(lms, RIGHT_PTS)
        top, bottom = _mean(lms, TOP_PTS), _mean(lms, BOTTOM_PTS)
    except (IndexError, TypeError, ZeroDivisionError):
        return None
    width, height = abs(right[0] - left[0]), abs(bottom[1] - top[1])
    if width < 0.03 or height < 0.03:
        return None
    return ((nose[0] - (left[0] + right[0]) / 2) / width, (nose[1] - (top[1] + bottom[1]) / 2) / height)


def pose_angles(matrix):
    """(lacet, tangage) en radians depuis la matrice 4x4 de MediaPipe : direction vers laquelle le visage
    regarde (3e colonne de la rotation). None si la matrice est absente ou illisible."""
    try:
        fx, fy, fz = float(matrix[0][2]), float(matrix[1][2]), float(matrix[2][2])
    except (IndexError, TypeError, ValueError):
        return None
    if fx == fy == fz == 0:
        return None
    return math.atan2(fx, fz), math.atan2(fy, math.hypot(fx, fz))


class HeadPointer:
    """Point virtuel 0..1 piloté par l'orientation de la tête ; référence prise au premier visage après reset()."""

    def __init__(self, scale=1.4, scale_y=2.0, rel_scale=1.5, rel_scale_y=3.0):
        from .filters import OneEuro
        self.scale, self.scale_y = scale, scale_y              # par radian
        self.rel_scale, self.rel_scale_y = rel_scale, rel_scale_y   # repli sans matrice
        self.fx, self.fy = OneEuro(POSE_MIN_CUTOFF, POSE_BETA), OneEuro(POSE_MIN_CUTOFF, POSE_BETA)
        self.sign = [1, -1]        # théorie : tourner à droite = lacet +, lever la tête = tangage +
        self.votes = [0, 0]
        self.base = self.base_rel = self.held = None

    def reset(self):
        self.base = self.base_rel = self.held = None
        self.fx.reset()
        self.fy.reset()

    def _check_sign(self, axis, d_pose, d_rel):
        """Le point doit bouger dans le même sens que le nez par rapport au visage (sens sûr)."""
        if abs(d_rel) < REL_MOVE or abs(d_pose) < POSE_MOVE:
            return
        agree = (self.sign[axis] * d_pose > 0) == (d_rel > 0)
        self.votes[axis] = 0 if agree else self.votes[axis] + 1
        if self.votes[axis] >= SIGN_VOTES:
            self.sign[axis] = -self.sign[axis]
            self.votes[axis] = 0
            import logging
            logging.getLogger("motionzero").info("tete : sens de l'axe %s corrige", "horizontal vertical".split()[axis])

    def point(self, lms, matrix=None, t=None):
        rel = head_offsets(lms) if lms is not None else None
        pose = pose_angles(matrix) if matrix is not None else None
        if pose is None:
            if rel is None:
                return None
            return self._from_rel(rel)
        if t is not None:
            pose = (self.fx(pose[0], t), self.fy(pose[1], t))
        if self.held is not None and max(abs(pose[0] - self.held[0]), abs(pose[1] - self.held[1])) < POSE_DEADZONE:
            pose = self.held                       # micro-variation : on ne bouge pas
        self.held = pose
        if self.base is None:
            self.base, self.base_rel = pose, rel   # tête maintenant = centre de l'écran
        d = (pose[0] - self.base[0], pose[1] - self.base[1])
        if rel is not None and self.base_rel is not None:
            for axis in (0, 1):
                self._check_sign(axis, d[axis], rel[axis] - self.base_rel[axis])
        x = 0.5 + self.scale * self.sign[0] * d[0]
        y = 0.5 + self.scale_y * self.sign[1] * d[1]
        return (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))

    def _from_rel(self, rel):
        if self.base_rel is None:
            self.base_rel = rel
        x = 0.5 + self.rel_scale * (rel[0] - self.base_rel[0])
        y = 0.5 + self.rel_scale_y * (rel[1] - self.base_rel[1])
        return (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))
