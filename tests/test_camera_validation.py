"""Validation d'image, sans caméra : images fabriquées."""
import numpy as np

from motionzero.camera import frame_is_valid


def _scene():
    y, x = np.mgrid[0:480, 0:640]
    img = np.stack([(x / 640 * 200), (y / 480 * 200), np.full_like(x, 90.0)], axis=-1)
    return img.astype(np.uint8)


def test_image_normale_valide():
    assert frame_is_valid(_scene())


def test_neige_sur_le_haut_rejetee():
    img = _scene()
    rng = np.random.default_rng(0)
    img[:336] = rng.integers(60, 200, size=(336, 640, 3), dtype=np.uint8)  # 70 % du haut en neige
    assert not frame_is_valid(img)


def test_image_uniforme_rejetee():
    assert not frame_is_valid(np.full((480, 640, 3), 128, np.uint8))


def test_image_absente_rejetee():
    assert not frame_is_valid(None)


def test_scene_tres_texturee_acceptee():
    """Mur crépi, rideau à motifs, plein jour : beaucoup de détail mais voisins corrélés."""
    import cv2
    rng = np.random.default_rng(1)
    tex = cv2.GaussianBlur(rng.integers(0, 255, size=(480, 640), dtype=np.uint8), (0, 0), 5.0)
    tex = cv2.normalize(tex, None, 0, 255, cv2.NORM_MINMAX)
    img = np.dstack([tex] * 3)
    assert frame_is_valid(img)
