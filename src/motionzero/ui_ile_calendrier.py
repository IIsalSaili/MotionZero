"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52) : méthodes de _IslandPainter (CalendrierMixin, découpé de ui_ile.py, #52)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from .ui_ile_base import BLUE, CAL_H, CAL_W, ISLAND_H, ISLAND_TOP, ISLET, ISLET_GAP, ORANGE


class CalendrierMixin:

    def _paint_calendar(self, p, cal):
        """« iris calendrier » : ruban du mois, 7 cartes de la semaine (ou un jour en grand), consignes."""
        gx = (self.width - (ISLET + ISLET_GAP + 300)) / 2
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)
        # en-tête dans l'île
        x0 = gx + ISLET + ISLET_GAP
        y0 = ISLAND_TOP + (ISLET - ISLAND_H) / 2
        fm_mode = QFontMetrics(self.font_mode)
        head = f"{cal['title']}"
        w = 20 + 10 + 10 + fm_mode.horizontalAdvance("CALENDRIER") + 14 + QFontMetrics(self.font_msg).horizontalAdvance(head) + 20
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x0, y0, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(x0 + 25, y0 + ISLAND_H / 2), 5, 5)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_mode)
        p.drawText(QRectF(x0 + 40, y0, 400, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, "CALENDRIER")
        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x0 + 54 + fm_mode.horizontalAdvance("CALENDRIER"), y0, 600, ISLAND_H),
                   Qt.AlignmentFlag.AlignVCenter, head)

        left = (self.width - CAL_W) / 2
        top = ISLAND_TOP + ISLET + 14
        # ruban du mois
        strip = cal["strip"]
        cell, gap = 26, 4
        fm_s = QFontMetrics(self.font_small)
        label_w = fm_s.horizontalAdvance(cal["month"]) + 16
        sw = 32 + label_w + len(strip) * (cell + gap) - gap
        sx = (self.width - sw) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 230))
        p.drawRoundedRect(QRectF(sx, top, sw, 44), 18, 18)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_small)
        p.drawText(QRectF(sx + 16, top, label_w, 44), Qt.AlignmentFlag.AlignVCenter, cal["month"])
        cx = sx + 16 + label_w
        bold = QFont(self.font_small)
        bold.setBold(True)
        p.setFont(bold)
        for d in strip:
            r = QRectF(cx, top + 9, cell, cell)
            if d["today"]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(BLUE)
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QColor(11, 13, 16))
            elif d["week"]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(42, 48, 58))
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QColor(255, 255, 255))
            else:
                p.setPen(ORANGE if d["kind"] == "a" else BLUE.lighter(125) if d["kind"] else QColor(120, 128, 140))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(d["n"]))
            cx += cell + gap
        top += 56

        if cal.get("detail"):
            self._paint_cal_day(p, left, top, cal["detail"])
        else:
            self._paint_cal_week(p, left, top, cal["days"])

        hint = ("« suivant » / « précédent » : jour · « lundi »… : autre jour · « ferme »" if cal.get("detail") else
                "« suivant » / « précédent » · « jeudi » : le jour en grand · « dix-huit » / « premier janvier » · « ferme »")
        hw = fm_s.horizontalAdvance(hint) + 36
        hy = top + CAL_H - 44 + 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 230))
        p.drawRoundedRect(QRectF((self.width - hw) / 2, hy, hw, 34), 16, 16)
        p.setPen(QColor(200, 205, 214))
        p.setFont(self.font_small)
        p.drawText(QRectF((self.width - hw) / 2, hy, hw, 34), Qt.AlignmentFlag.AlignCenter, hint)
        p.restore()

    def _paint_cal_week(self, p, left, top, days):
        gap = 10
        cw = (CAL_W - 6 * gap) / 7
        ch = CAL_H - 56
        f_name = QFont(self.font_small)
        f_name.setBold(True)
        f_name.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        f_num = QFont("Atkinson Hyperlegible", 34, QFont.Weight.Bold)
        f_time = QFont(self.font_small)
        f_time.setBold(True)
        f_txt = QFont("Atkinson Hyperlegible", 13, QFont.Weight.Bold)
        f_rout = QFont("Atkinson Hyperlegible", 10)
        for i, d in enumerate(days):
            x = left + i * (cw + gap)
            p.save()
            if d["past"]:
                p.setOpacity(0.55)
            p.setPen(QPen(BLUE, 2) if d["today"] or d["focus"] else Qt.PenStyle.NoPen)
            p.setBrush(QColor(31, 42, 68, 245) if d["today"] else QColor(0, 0, 0, 240))
            p.drawRoundedRect(QRectF(x, top, cw, ch), 18, 18)
            inner = cw - 24
            y = top + 14
            p.setPen(QColor(154, 163, 176))
            p.setFont(f_name)
            p.drawText(QRectF(x + 12, y, inner, 18), Qt.AlignmentFlag.AlignLeft, d["name"])
            y += 20
            p.setPen(QColor(255, 255, 255))
            p.setFont(f_num)
            p.drawText(QRectF(x + 12, y, inner, 44), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(d["n"]))
            y += 50
            p.setPen(QColor(38, 42, 49))
            p.drawLine(QPointF(x + 12, y), QPointF(x + cw - 12, y))
            y += 10
            for e in d["items"]:
                p.setPen(ORANGE if e["alarm"] else BLUE.lighter(130))
                p.setFont(f_time)
                p.drawText(QRectF(x + 12, y, inner, 18), Qt.AlignmentFlag.AlignLeft,
                           e["t"] + (" · alarme" if e["alarm"] else ""))
                y += 18
                p.setPen(QColor(255, 255, 255))
                p.setFont(f_txt)
                fm = QFontMetrics(f_txt)
                p.drawText(QRectF(x + 12, y, inner, 20), Qt.AlignmentFlag.AlignLeft,
                           fm.elidedText(e["txt"], Qt.TextElideMode.ElideRight, int(inner)))
                y += 28
            if d["more"]:
                p.setPen(QColor(184, 190, 200))
                p.setFont(f_time)
                p.drawText(QRectF(x + 12, y, inner, 18), Qt.AlignmentFlag.AlignLeft, f"+ {d['more']} autre{'s' if d['more'] > 1 else ''}")
            if d["routine"]:
                p.setPen(QColor(138, 147, 163))
                p.setFont(f_rout)
                flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom) | int(Qt.TextFlag.TextWordWrap)
                p.drawText(QRectF(x + 12, top + ch - 100, inner, 88), flags, "\n".join(d["routine"]))
            p.restore()

    def _paint_cal_day(self, p, left, top, day):
        ch = CAL_H - 56
        p.setPen(QPen(BLUE, 2) if day["today"] else Qt.PenStyle.NoPen)
        p.setBrush(QColor(31, 42, 68, 245) if day["today"] else QColor(0, 0, 0, 240))
        p.drawRoundedRect(QRectF(left, top, CAL_W, ch), 22, 22)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Atkinson Hyperlegible", 26, QFont.Weight.Bold))
        p.drawText(QRectF(left + 28, top + 14, CAL_W - 56, 40), Qt.AlignmentFlag.AlignVCenter, day["title"])
        items = day["items"]
        if not items:
            p.setPen(QColor(184, 190, 200))
            p.setFont(self.font_answer)
            p.drawText(QRectF(left + 28, top + 70, CAL_W - 56, 30), Qt.AlignmentFlag.AlignVCenter, "Rien ce jour-là.")
            return
        per_col = 8
        cols = min(3, (len(items) + per_col - 1) // per_col)
        colw = (CAL_W - 56) / max(cols, 1)
        f_t = QFont("Atkinson Hyperlegible", 17, QFont.Weight.Bold)
        f_x = QFont("Atkinson Hyperlegible", 17)
        for i, e in enumerate(items[:per_col * 3]):
            c, r = divmod(i, per_col)
            x = left + 28 + c * colw
            y = top + 70 + r * 40
            col = ORANGE if e["alarm"] else (QColor(107, 114, 128) if e["routine"] else BLUE)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            if e["alarm"]:
                p.drawRoundedRect(QRectF(x, y + 9, 13, 13), 3, 3)
            else:
                p.drawEllipse(QRectF(x, y + 9, 13, 13))
            p.setPen(QColor(255, 255, 255))
            p.setFont(f_t)
            p.drawText(QRectF(x + 24, y, 80, 32), Qt.AlignmentFlag.AlignVCenter, e["t"])
            p.setFont(f_x)
            fm = QFontMetrics(f_x)
            p.drawText(QRectF(x + 104, y, colw - 116, 32), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(e["txt"], Qt.TextElideMode.ElideRight, int(colw - 116)))
