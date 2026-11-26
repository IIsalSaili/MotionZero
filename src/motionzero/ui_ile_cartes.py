"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52) : méthodes de _IslandPainter (CartesMixin, découpé de ui_ile.py, #52)."""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from .ui_ile_base import ALARM_RED, ANSWER_MAX_H, ANSWER_W, BLUE, HELP_H, HELP_W, ICON, ISLAND_H, ISLAND_TOP, ISLET, ISLET_GAP, ORANGE, REMINDER_W, fit_font, reminder_texts


class CartesMixin:

    def _paint_answer(self, p, mode, header):
        """L'île agrandie vers le bas : en-tête, la question en petit, la réponse, le temps restant."""
        qa = self.qa
        pad, top = 20, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        gx = (self.width - (ISLET + ISLET_GAP + ANSWER_W)) / 2
        x = gx + ISLET + ISLET_GAP
        inner = ANSWER_W - 2 * pad
        fm_q = QFontMetrics(self.font_small)
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        q_text = f"« {qa.get('question')} »" if qa.get("question") else ""
        q_rect = fm_q.boundingRect(QRect(0, 0, inner, 100000), flags, q_text) if q_text else QRect()
        room = ANSWER_MAX_H - 44 - (q_rect.height() + 8 if q_text else 0) - 40
        font_a = fit_font(self.font_answer, qa.get("answer") or "", inner, room)   # tout le texte, police ajustée
        fm_a = QFontMetrics(font_a)
        a_rect = fm_a.boundingRect(QRect(0, 0, inner, 100000), flags, qa.get("answer") or "")
        meta = f"Iris · disparaît dans {int(qa.get('left', 0))} s · « Iris, ferme » pour la retirer"
        h = min(ANSWER_MAX_H, 44 + (q_rect.height() + 8 if q_text else 0) + a_rect.height() + 40)
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 240))
        p.drawRoundedRect(QRectF(x, top, ANSWER_W, h), 22, 22)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(x + pad + 5, top + 23), 5, 5)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(x + pad + 20, top, inner, 46), Qt.AlignmentFlag.AlignVCenter, mode)
        fm_mode = QFontMetrics(self.font_mode)
        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + 34 + fm_mode.horizontalAdvance(mode), top, inner, 46),
                   Qt.AlignmentFlag.AlignVCenter, header)
        y = top + 44
        if q_text:
            p.setPen(QColor(255, 255, 255, 150))
            p.setFont(self.font_small)
            p.drawText(QRectF(x + pad, y, inner, q_rect.height()), flags, q_text)
            y += q_rect.height() + 8
        p.setPen(QColor(255, 255, 255))
        p.setFont(font_a)
        p.save()
        p.setClipRect(QRectF(x + pad, y, inner, max(0, top + h - 36 - y)))   # jamais sur la ligne du bas
        p.drawText(QRectF(x + pad, y, inner, a_rect.height()), flags, qa.get("answer") or "")
        p.restore()
        p.setPen(QColor(255, 255, 255, 110))
        p.setFont(self.font_small)
        p.setFont(fit_font(self.font_small, meta, inner))
        p.drawText(QRectF(x + pad, top + h - 28, inner, 22), Qt.AlignmentFlag.AlignVCenter, meta)
        p.restore()

    def _paint_help(self, p, hv):
        """« iris aide » : en haut ce qui marche maintenant (mode en cours), puis toutes les commandes en 4 colonnes,
        une commande par ligne (mot en blanc, effet en gris). Le fond prend la hauteur du contenu."""
        fm = QFontMetrics(self.font_small)
        bold = QFont(self.font_small)
        bold.setBold(True)
        fmb = QFontMetrics(bold)
        pad, line, chip_h = 24, fm.height() + 6, fm.height() + 10
        left, top = (self.width - HELP_W) / 2, ISLAND_TOP
        inner = HELP_W - 2 * pad
        # 1. mise en place (positions), 2. dessin
        chips, x, y = [], 0.0, 38 + line + 4
        for word, what in hv["now"]["rows"]:
            w = fmb.horizontalAdvance(word) + 10 + fm.horizontalAdvance(what) + 24
            if x and x + w > inner:
                x, y = 0.0, y + chip_h + 6
            chips.append((x, y, w, word, what))
            x += w + 8
        y0 = y + chip_h + 22
        cols, gap = 4, 22
        colw = (inner - (cols - 1) * gap) / cols
        heights, cells = [0.0] * cols, []
        for theme, rows in hv["groups"]:
            c = heights.index(min(heights))
            cells.append((c, heights[c], theme, rows))
            heights[c] += line * (len(rows) + 1) + 16
        h = min(y0 + max(heights) + pad, HELP_H)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(left, top, HELP_W, h), 22, 22)
        L, T = left + pad, top + pad
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(L, T, inner, 26), Qt.AlignmentFlag.AlignVCenter, "AIDE · dis « iris » puis un mot")
        p.setPen(QColor(200, 205, 214))
        p.setFont(self.font_small)
        p.drawText(QRectF(L, T, inner, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "« ferme » ou « merci » pour fermer")
        p.setPen(BLUE)
        p.setFont(bold)
        p.drawText(QRectF(L, T + 38, inner, line), Qt.AlignmentFlag.AlignVCenter, hv["now"]["title"])
        for x, y, w, word, what in chips:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(111, 155, 245, 60))
            p.drawRoundedRect(QRectF(L + x, T + y, w, chip_h), chip_h / 2, chip_h / 2)
            p.setPen(QColor(255, 255, 255))
            p.setFont(bold)
            p.drawText(QRectF(L + x + 12, T + y, w, chip_h), Qt.AlignmentFlag.AlignVCenter, word)
            p.setPen(QColor(200, 205, 214))
            p.setFont(self.font_small)
            p.drawText(QRectF(L + x + 22 + fmb.horizontalAdvance(word), T + y, w, chip_h),
                       Qt.AlignmentFlag.AlignVCenter, what)
        for c, dy, theme, rows in cells:
            cx, cy = L + c * (colw + gap), T + y0 + dy
            p.setPen(ORANGE)
            p.setFont(bold)
            p.drawText(QRectF(cx, cy, colw, line), Qt.AlignmentFlag.AlignVCenter, theme.upper())
            for word, what in rows:
                cy += line
                ww = fmb.horizontalAdvance(word)
                p.setPen(QColor(255, 255, 255))
                p.setFont(bold)
                p.drawText(QRectF(cx, cy, colw, line), Qt.AlignmentFlag.AlignVCenter, word)
                p.setPen(QColor(170, 176, 188))
                p.setFont(self.font_small)
                room = int(colw - ww - 10)
                p.drawText(QRectF(cx + ww + 10, cy, room, line), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(what, Qt.TextElideMode.ElideRight, room))
        p.restore()

    def _paint_reminder(self, p, kind, data, at=None):
        """Carte du rappel déclenché (rouge qui pulse si l'alarme sonne) ou liste des rappels."""
        import time as _t
        pad, top = 22, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        gx = (self.width - (ISLET + ISLET_GAP + REMINDER_W)) / 2
        x = gx + ISLET + ISLET_GAP
        if at is not None:                     # coin haut droit : le logo reste au centre, dessiné à part
            x, top = at
        inner = REMINDER_W - 2 * pad
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        title, body, meta = reminder_texts(kind, data)
        font_body = fit_font(self.font_rem if kind == "current" else self.font_answer, body, inner,
                             ANSWER_MAX_H - 46 - 44)       # tout le texte : la police rapetisse s'il le faut
        font_title = fit_font(self.font_mode, title, inner - ICON - 10)
        font_meta = fit_font(self.font_small, meta, inner)
        alarm = kind == "current" and data.get("alarm")
        ringing = kind == "current" and data.get("ringing")
        fm_b, fm_s = QFontMetrics(font_body), QFontMetrics(font_meta)
        b_rect = fm_b.boundingRect(QRect(0, 0, inner, 100000), flags, body)
        h = min(ANSWER_MAX_H, 46 + b_rect.height() + 44)
        if ringing:      # pulsation : 1 s, entre rouge sombre et rouge vif (rouge vif fixe sans animation)
            k = 0.5 + 0.5 * math.sin(_t.monotonic() * 2 * math.pi) if getattr(self, "motion", True) else 1.0
            bg = QColor(int(ALARM_RED[0] * (0.6 + 0.4 * k)), ALARM_RED[1], ALARM_RED[2], 245)
        elif alarm:
            bg = QColor(120, 20, 28, 240)
        elif kind == "current":
            bg = QColor(28, 38, 70, 245)       # bleu nuit : se distingue du noir habituel
        else:
            bg = QColor(0, 0, 0, 240)
        p.save()
        if at is None:
            self._paint_islet(p, gx, ISLAND_TOP)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(x, top, REMINDER_W, h), 22, 22)
        bell = self.icons.get("bell")
        if bell is not None:
            bell.render(p, QRectF(x + pad, top + 11, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(font_title)
        p.drawText(QRectF(x + pad + ICON + 10, top, inner - ICON - 10, 46), Qt.AlignmentFlag.AlignVCenter, title)
        p.setFont(font_body)
        p.save()
        p.setClipRect(QRectF(x + pad, top + 46, inner, max(0, h - 46 - 36)))
        p.drawText(QRectF(x + pad, top + 46, inner, b_rect.height()), flags, body)
        p.restore()
        p.setPen(QColor(255, 255, 255, 170))
        p.setFont(font_meta)
        p.drawText(QRectF(x + pad, top + h - 30, inner, 22), Qt.AlignmentFlag.AlignVCenter,
                   fm_s.elidedText(meta, Qt.TextElideMode.ElideRight, inner))
        p.restore()

    def _paint_discord(self, p, islet_x, y):
        """Pastille noire à gauche de l'îlot, icônes rouges ; ne s'estompe jamais, comme le logo.
        La pastille du prochain rappel se place encore à sa gauche."""
        if not self.discord:
            return
        pad, gap = 12, 6
        w = 2 * pad + len(self.discord) * ICON + (len(self.discord) - 1) * gap
        x = islet_x - ISLET_GAP - w
        top = y + (ISLET - ISLAND_H) / 2
        p.save()
        p.setOpacity(1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, top, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        ix = x + pad
        for name in self.discord:
            r = self.icons.get(name)
            if r is not None:
                r.render(p, QRectF(ix, top + (ISLAND_H - ICON) / 2, ICON, ICON))
            ix += ICON + gap
        p.restore()
