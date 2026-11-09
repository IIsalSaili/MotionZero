"""Interface Qt. Étape 1 du plan overlay : une simple fenêtre d'aperçu qui remplace cv2.imshow.

Le moteur (caméra, MediaPipe, Core) tourne dans un autre fil et envoie ses images par Bridge.
Les signaux Qt émis depuis ce fil arrivent dans le fil de l'interface par la file d'attente Qt.
"""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

__all__ = ["Bridge", "PreviewWindow", "QApplication"]


class Bridge(QObject):
    frame = Signal(object)   # image BGR (numpy) déjà dessinée par overlay.render
    done = Signal()          # le moteur s'est arrêté


class PreviewWindow(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("motionzero")
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setText("Démarrage de la caméra…")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label)
        self._sized = False

    def set_frame(self, img):
        h, w = img.shape[:2]
        # BGR -> QImage ; .copy() car le tableau numpy peut être réutilisé par le moteur
        qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888).copy()
        self.label.setPixmap(QPixmap.fromImage(qimg))
        if not self._sized:
            self.resize(w, h)
            self._sized = True

    def closeEvent(self, event):
        self.closed.emit()     # fenêtre fermée = STOP, comme avant
        super().closeEvent(event)
