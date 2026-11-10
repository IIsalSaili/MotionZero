"""Prépare les logos d'Iris pour l'île : retire le fond blanc, recadre, réduit.

  python tools/prepare_logos.py "C:/Users/ilias/Desktop/iris logo"

Le fond retiré = le blanc relié au bord de l'image (entre les doigts compris). Le blanc et le gris
de l'œil, entourés par la main, restent intacts. Les bords sont adoucis selon leur clarté.
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "iris")
SIZE = 192          # hauteur en pixels (affiché ~54 px : marge pour les écrans à forte densité)
FILES = {"1": "neutre", "2": "neutre_ferme", "3": "ok", "4": "lecture", "5": "lecture_ferme",
         "6": "souris", "7": "souris_ferme"}


def detour(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white = (gray >= 245).astype(np.uint8)          # le liseré gris de l'œil (~236) n'est pas touché
    _, lab = cv2.connectedComponents(white, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    near = cv2.dilate(bg.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~bg
    alpha = np.full(gray.shape, 255, np.uint8)
    alpha[bg] = 0
    soft = np.clip((255 - gray.astype(np.int32)) * 255 // 60, 0, 255).astype(np.uint8)
    alpha[near] = np.minimum(alpha[near], soft[near])
    return np.dstack([img, alpha])


def main():
    src = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    imgs = {name: detour(os.path.join(src, f"{num}.png")) for num, name in FILES.items()}
    # même recadrage pour toutes : l'œil ne doit pas sauter quand on change d'image
    ys, xs = np.where(np.max([im[:, :, 3] for im in imgs.values()], axis=0) > 0)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    for name, im in imgs.items():
        crop = im[y0:y1, x0:x1]
        w = round(crop.shape[1] * SIZE / crop.shape[0])
        small = cv2.resize(crop, (w, SIZE), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(OUT, f"{name}.png"), small)
        print(name, small.shape[1], "x", small.shape[0])


if __name__ == "__main__":
    main()
