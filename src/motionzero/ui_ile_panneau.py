"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52) : méthodes de _IslandPainter (PanneauMixin, découpé de ui_ile.py, #52)."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from .ui_ile_base import CAND, ISLAND_TOP, ISLET, ORANGE, PANEL_BOTTOM, PANEL_MARGIN, PANEL_W, chip_rows
from .ui_ile_base2 import CAM_BOX, CAM_MARGIN, QUOTA_MARGIN, cam_blink, paint_claude_logo


class PanneauMixin:

    def _paint_cam_down(self, p):
        """Caméra en panne : caméra barrée en bas à gauche, qui clignote (pas de texte, 24/11)."""
        x, y = CAM_MARGIN, self.height - CAM_MARGIN - CAM_BOX
        k = cam_blink(getattr(self, "anim_now", 0.0), self.motion)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 220))
        p.drawRoundedRect(QRectF(x, y, CAM_BOX, CAM_BOX), CAM_BOX / 2, CAM_BOX / 2)
        icon = self.icons.get("camera-off")
        if icon is not None:
            p.setOpacity(k)
            m = CAM_BOX * 0.24
            icon.render(p, QRectF(x + m, y + m, CAM_BOX - 2 * m, CAM_BOX - 2 * m))
        p.restore()

    def _paint_cand_panel(self, p, pn):
        """« iris candidature » : panneau à droite, le site reste visible à gauche (maquette A1)."""
        big = QFont("Atkinson Hyperlegible", 20, QFont.Weight.Bold)
        num = QFont("Atkinson Hyperlegible", 18, QFont.Weight.Bold)
        word = QFont("Atkinson Hyperlegible", 15, QFont.Weight.Bold)
        small, msgf = self.font_small, self.font_msg
        grey, light, white = QColor(166, 166, 176), QColor(201, 201, 209), QColor(242, 242, 245)
        surf, chip = QColor(23, 23, 28), QColor(36, 36, 43)
        x0 = self.width - PANEL_W - PANEL_MARGIN
        h = self.height - PANEL_MARGIN - PANEL_BOTTOM
        pad = 24
        x, inner = x0 + pad, PANEL_W - 2 * pad
        p.save()
        p.setPen(QColor(42, 42, 50))
        p.setBrush(QColor(11, 11, 14, 245))
        p.drawRoundedRect(QRectF(x0, PANEL_MARGIN, PANEL_W, h), 18, 18)
        y = PANEL_MARGIN + 22
        # en-tête
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(CAND)
        p.drawEllipse(QPointF(x + 5, y + 12), 5, 5)
        p.setPen(white)
        p.setFont(self.font_mode)
        p.drawText(QRectF(x + 18, y, 220, 24), Qt.AlignmentFlag.AlignVCenter, "CANDIDATURE")
        p.setPen(grey)
        p.setFont(small)
        status = pn.get("status") or ""
        if pn.get("busy"):
            status = "CVGEN travaille…"
        p.drawText(QRectF(x, y, inner, 24), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), status)
        y += 40
        # chiffres
        tiles = pn.get("tiles") or []
        if tiles:
            tw = (inner - 6 * (len(tiles) - 1)) / len(tiles)
            for k, (n, lbl, on) in enumerate(tiles):
                r = QRectF(x + k * (tw + 6), y, tw, 60)
                p.setPen(CAND if on else Qt.PenStyle.NoPen)
                p.setBrush(surf)
                p.drawRoundedRect(r, 8, 8)
                p.setPen(white)
                p.setFont(num)
                p.drawText(QRectF(r.x(), r.y() + 6, tw, 28), Qt.AlignmentFlag.AlignCenter, str(n))
                p.setPen(grey)
                p.setFont(small)
                p.drawText(QRectF(r.x(), r.y() + 34, tw, 20), Qt.AlignmentFlag.AlignCenter, lbl)
            y += 76
        # bas : les mots à dire (fixés en bas du panneau)
        words = (pn.get("words") or [])[:4]
        extra = pn.get("extra") or []
        rows = (len(words) + 1) // 2
        bottom = PANEL_MARGIN + h - 22
        foot_y = bottom - 20
        p.setPen(QColor(138, 142, 154))
        p.setFont(small)
        p.drawText(QRectF(x, foot_y, inner, 20), Qt.AlignmentFlag.AlignCenter, pn.get("foot") or "")
        # autres mots de l'étape : une ligne chacun, « mots » à gauche, effet à droite
        fm_s = QFontMetrics(small)
        ex_y = foot_y - 10 - len(extra) * 42
        bold_s = QFont(small)
        bold_s.setBold(True)
        for k, (mots, quoi) in enumerate(extra):  # le mot en blanc, dessous ce qu'il fait
            ry = ex_y + k * 42
            p.setPen(white)
            p.setFont(bold_s)
            p.drawText(QRectF(x, ry, inner, 20), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(bold_s).elidedText(mots, Qt.TextElideMode.ElideRight, int(inner)))
            p.setPen(grey)
            p.setFont(small)
            p.drawText(QRectF(x, ry + 19, inner, 20), Qt.AlignmentFlag.AlignVCenter,
                       fm_s.elidedText(quoi, Qt.TextElideMode.ElideRight, int(inner)))
        if extra:
            p.setPen(QColor(138, 142, 154))
            p.drawText(QRectF(x, ex_y - 26, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Aussi")
            ex_y -= 34
        th = 86                                    # bouton : le mot, et dessous ce qu'il fait
        grid_h = rows * th + max(rows - 1, 0) * 8
        grid_y = ex_y - 8 - grid_h
        if words:
            p.setPen(QColor(138, 142, 154))
            p.drawText(QRectF(x, grid_y - 24, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Tu peux dire")
            ww = (inner - 8) / 2
            for k, (w, quoi) in enumerate(words):
                r = QRectF(x + (k % 2) * (ww + 8), grid_y + (k // 2) * (th + 8), ww, th)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(CAND if k == 0 else chip)
                p.drawRoundedRect(r, 10, 10)
                p.setPen(QColor(11, 11, 14) if k == 0 else white)
                p.setFont(word)
                p.drawText(QRectF(r.x(), r.y() + 8, ww, 26), Qt.AlignmentFlag.AlignCenter, w)
                p.setPen(QColor(30, 50, 44) if k == 0 else grey)
                p.setFont(small)
                p.drawText(QRectF(r.x() + 8, r.y() + 34, ww - 16, th - 38),
                           int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                           quoi)
        room = grid_y - 36 - y                     # place pour la carte et la suite
        # carte : l'offre, ou un message
        card_top = y
        p.save()
        p.setClipRect(QRectF(x0, card_top, PANEL_W, max(room, 0)))
        cx, cw = x + 18, inner - 36
        cy = card_top + 18
        o, m = pn.get("offer"), pn.get("msg")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(surf)
        # hauteur d'abord mesurée en dessinant sur une couche : plus simple de dessiner le fond après coup
        layer_start = cy
        texts = []
        if o:
            texts.append(("row", o["pos"], o.get("source") or ""))
            texts.append(("wrap", big, white, o["poste"], 60))
            texts.append(("wrap", msgf, light, o["entreprise"], 44))
            if o.get("chips"):
                texts.append(("chips", o["chips"]))
            texts.append(("note", o["note"], o["frac"]))
            for sign, t in (("+ ", o.get("plus")), ("- ", o.get("minus"))):
                if t:
                    texts.append(("wrap", small, light, sign + t, 66))
            if o.get("prep"):
                texts.append(("wrap", small, ORANGE, o["prep"], 40))
        elif m:
            texts.append(("wrap", big, white, m.get("title") or "Candidature", 60))
            for line in m.get("lines") or []:
                texts.append(("wrap", msgf, light, line, 70))
        # fond de la carte : hauteur estimée par une première passe sans dessin
        def measure(item):
            if item[0] == "row":
                return 20
            if item[0] == "wrap":
                flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
                return min(QFontMetrics(item[1]).boundingRect(QRect(0, 0, int(cw), 100000), flags, item[3]).height(),
                           item[4])
            if item[0] == "chips":
                return 32 * len(chip_rows(QFontMetrics(small).horizontalAdvance, item[1], cw)) - 6
            return 34
        card_h = 36 + sum(measure(it) for it in texts) + 10 * max(len(texts) - 1, 0)
        card_h = min(card_h, max(room, 0))
        p.drawRoundedRect(QRectF(x, card_top, inner, card_h), 14, 14)
        cy = layer_start
        for it in texts:
            if it[0] == "row":
                p.setFont(small)
                p.setPen(grey)
                p.drawText(QRectF(cx, cy, cw, 20), Qt.AlignmentFlag.AlignVCenter, it[1])
                p.drawText(QRectF(cx, cy, cw, 20), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), it[2])
                cy += 20
            elif it[0] == "wrap":
                cy += self._wrap(p, it[1], it[2], cx, cy, cw, it[3], it[4])
            elif it[0] == "chips":                # sur plusieurs lignes si besoin (#64 : ville, télétravail, salaire)
                fm = QFontMetrics(small)
                for row in chip_rows(fm.horizontalAdvance, it[1], cw):
                    px = cx
                    for c in row:
                        cwid = fm.horizontalAdvance(c) + 18
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(chip)
                        p.drawRoundedRect(QRectF(px, cy, cwid, 26), 13, 13)
                        p.setPen(white)
                        p.setFont(small)
                        p.drawText(QRectF(px, cy, cwid, 26), Qt.AlignmentFlag.AlignCenter, c)
                        px += cwid + 6
                    cy += 32
                cy -= 6
            else:
                p.setPen(CAND)
                p.setFont(QFont("Atkinson Hyperlegible", 24, QFont.Weight.Bold))
                nw = QFontMetrics(p.font()).horizontalAdvance(it[1]) + 12
                p.drawText(QRectF(cx, cy, nw, 34), Qt.AlignmentFlag.AlignVCenter, it[1])
                bx, bw = cx + nw, cw - nw - 34
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(42, 42, 50))
                p.drawRoundedRect(QRectF(bx, cy + 14, bw, 6), 3, 3)
                p.setBrush(CAND)
                p.drawRoundedRect(QRectF(bx, cy + 14, bw * it[2], 6), 3, 3)
                p.setPen(grey)
                p.setFont(small)
                p.drawText(QRectF(bx + bw, cy, 34, 34), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), "/ 5")
                cy += 34
            cy += 10
        y = card_top + card_h + 12
        if pn.get("note"):
            y += self._wrap(p, msgf, CAND, x, y, inner, pn["note"], 48) + 10
        nxt = pn.get("next") or []
        if nxt and y + 30 < card_top + room:
            p.setPen(QColor(138, 142, 154))
            p.setFont(small)
            p.drawText(QRectF(x, y, inner, 20), Qt.AlignmentFlag.AlignVCenter, "Ensuite")
            y += 24
            fm = QFontMetrics(small)
            for label, note in nxt:
                if y + 28 > card_top + room:
                    break
                p.setPen(grey)
                p.drawText(QRectF(x, y, inner - 40, 28), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(label, Qt.TextElideMode.ElideRight, int(inner - 40)))
                p.drawText(QRectF(x, y, inner, 28), int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignRight), note)
                y += 30
        p.restore()
        p.restore()

    def _paint_quota(self, p, lines):
        """Fiche du quota, coin haut gauche : logo Claude, session 5 h puis semaine dessous ; jamais estompée."""
        fm, fs = QFontMetrics(self.font_msg), QFontMetrics(self.font_small)
        pad, logo, gap = 12, 38, 12
        label_w = max(fs.horizontalAdvance(l) for l, _ in lines) + 8 if any(l for l, _ in lines) else 0
        w = pad + logo + gap + label_w + max(fm.horizontalAdvance(t) for _, t in lines) + pad + 6
        h = max(ISLET, 14 + 24 * len(lines))
        x, y = QUOTA_MARGIN, ISLAND_TOP + (ISLET - h) / 2   # coin haut gauche, centrée sur le bandeau
        p.save()
        p.setOpacity(1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, h), min(h / 2, 28), min(h / 2, 28))
        paint_claude_logo(p, x + pad + logo / 2, y + h / 2, logo / 2)
        ty = y + (h - 24 * len(lines)) / 2
        tx = x + pad + logo + gap
        for label, text in lines:
            if label:
                p.setFont(self.font_small)
                p.setPen(QColor(255, 255, 255, 150))
                p.drawText(QRectF(tx, ty, label_w, 24), Qt.AlignmentFlag.AlignVCenter, label)
            p.setFont(self.font_msg)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(tx + label_w, ty, w, 24), Qt.AlignmentFlag.AlignVCenter, text)
            ty += 24
        p.restore()
