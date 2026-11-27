"""Île en haut de l'écran, panneau candidature, calendrier, aide, rappels : dessin et calculs purs (découpé de ui.py, #52) : méthodes de _IslandPainter (PiecesMixin, découpé de ui_ile.py, #52)."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainterPath
from .ui_ile_base import CORNER_PAD, CORNER_RADIUS, CORNER_ROW, CORNER_W, PANEL_MARGIN, PANEL_W, REMINDER_W, CLOCK_BIG, CLOCK_GAP, ICON, ISLAND_H, ISLAND_TOP, ISLET, ISLET_GAP, TICKER_H, TICKER_W, clock_anim
from .ui_ile_base2 import paint_logo, ticker_offset


class PiecesMixin:

    def _wrap(self, p, font, color, x, y, w, text, max_h=10000):
        """Texte sur plusieurs lignes ; renvoie la hauteur utilisée (bornée à max_h)."""
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap)
        h = min(QFontMetrics(font).boundingRect(QRect(0, 0, int(w), 100000), flags, text).height(), max_h)
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(x, y, w, h), flags, text)
        return h

    def _paint_main(self, p):
        mode, msg = self.content[0], self.content[1]
        if self.help:
            self._paint_help(p, self.help)
            return
        if self.rem and self.rem[0] == "calendar":
            self._paint_calendar(p, self.rem[1])
            return
        if self.rem:
            self._paint_reminder(p, *self.rem)
            return
        if getattr(self, "qa", None):
            self._paint_answer(p, mode, msg)
            return
        fm_mode, fm_msg = QFontMetrics(self.font_mode), QFontMetrics(self.font_small)
        pad, dot, dgap = 22, 8, 10
        mode_w = (dot + dgap + fm_mode.horizontalAdvance(mode)) if mode else 0
        msg_w = fm_msg.horizontalAdvance(msg) if msg else 0
        w = 2 * pad + max(mode_w, min(msg_w, TICKER_W - 2 * pad)) if (mode or msg) else 0
        two = bool(mode and msg)                 # #18 : la même île s'agrandit, le texte sous les mots
        h = ISLAND_H + 20 if two else ISLAND_H
        gx = (self.width - (ISLET + (ISLET_GAP + w if w else 0))) / 2   # rien à dire : le logo seul, centré
        x, y = gx + ISLET + ISLET_GAP, ISLAND_TOP + (ISLET - ISLAND_H) / 2
        p.save()
        self._paint_islet(p, gx, ISLAND_TOP)       # le logo ne s'estompe jamais
        if w:
            p.setOpacity(self.opacity)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 235))                # noir opaque : lisible sur tout fond
            r = min(h, ISLAND_H) / 2
            p.drawRoundedRect(QRectF(x, y, w, h), r, r)
            line1 = (y + 7, 26) if two else (y, ISLAND_H)    # (haut, hauteur) de la ligne des mots
            if mode:
                mx = x + (w - mode_w) / 2                    # pastille + mots, centrés ensemble
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(QPointF(mx + dot / 2, line1[0] + line1[1] / 2), dot / 2, dot / 2)
                p.setPen(QColor(255, 255, 255))
                p.setFont(self.font_mode)
                p.drawText(QRectF(mx + dot + dgap, line1[0], fm_mode.horizontalAdvance(mode) + 2, line1[1]),
                           Qt.AlignmentFlag.AlignVCenter, mode)
            if msg:
                top, hh = (y + 33, 22) if two else (y, ISLAND_H)
                self._paint_ticker(p, x + pad, top, w - 2 * pad, msg, hh)
        p.restore()
        ty = y + h + CLOCK_GAP
        self._paint_clock(p, x, ty)
        if self.next_rem:
            ty += ISLAND_H + CLOCK_GAP
        if getattr(self, "alttab", None):
            self._paint_alttab(p, ty)

    def _paint_corner(self, p):
        """Coin haut droit (27/11) : un seul bloc collé aux bords de l'écran (angle carré contre le coin,
        seul l'angle bas gauche arrondi) ; lignes timer et chronomètre, puis le rappel déclenché.
        À gauche du panneau candidature s'il est ouvert. Rien ici ne cache le centre."""
        pills = getattr(self, "timer_pills", [])
        rem = getattr(self, "corner_rem", None)
        if not pills and not rem:
            return
        panel = bool(getattr(self, "panel", None))
        right = self.width - (PANEL_W + 2 * PANEL_MARGIN if panel else 0)
        fm = QFontMetrics(self.font_msg)
        cw = CORNER_W if rem else 22 + ICON + 10 + max(fm.horizontalAdvance(t) for t, _ in pills) + 28
        x = right - cw
        rows = len(pills) * CORNER_ROW + (CORNER_PAD if pills else 0)
        rem_h, rem_bg = self._paint_reminder(p, "current", rem, width=CORNER_W, measure=True) if rem else (0, None)
        h = rows + rem_h
        r = CORNER_RADIUS
        path = QPainterPath()
        path.moveTo(x, 0)
        path.lineTo(right, 0)
        if panel:                       # pas contre le bord droit : les deux angles du bas arrondis
            path.lineTo(right, h - r)
            path.quadTo(right, h, right - r, h)
        else:
            path.lineTo(right, h)
        path.lineTo(x + r, h)
        path.quadTo(x, h, x, h - r)
        path.closeSubpath()
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 240))
        p.drawPath(path)
        p.setClipPath(path)
        if rem:
            p.fillRect(QRectF(x, rows, CORNER_W, rem_h), rem_bg)
        y = CORNER_PAD / 2
        for text, countdown in pills:
            icon = self.icons.get("timer")
            if icon is not None:
                icon.render(p, QRectF(x + 22, y + (CORNER_ROW - ICON) / 2, ICON, ICON))
            p.setPen(QColor(150, 180, 255) if countdown else QColor(255, 255, 255))
            p.setFont(self.font_msg)
            room = int(cw - 22 - ICON - 10 - 22)
            p.drawText(QRectF(x + 22 + ICON + 10, y, room, CORNER_ROW), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, room))
            y += CORNER_ROW
        if pills and rem:
            p.setPen(QColor(255, 255, 255, 40))
            p.drawLine(QPointF(x, rows), QPointF(right, rows))
        p.restore()
        if rem:
            self._paint_reminder(p, "current", rem, at=(x, rows), width=CORNER_W, flush=True)

    def _pill_width(self, text):
        return 2 * 18 + ICON + 10 + QFontMetrics(self.font_msg).horizontalAdvance(text)

    def _paint_alttab(self, p, y):
        """« iris alt-tab » : bandeau des fenêtres numérotées, centré sur l'écran, sans animation du logo."""
        fm = QFontMetrics(self.font_msg)
        pad, gap = 18, 10
        w = 2 * pad + ICON + gap + fm.horizontalAdvance(self.alttab)
        x = (self.width - w) / 2
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        icon = self.icons.get("app-window")
        if icon is not None:
            icon.render(p, QRectF(x + pad, y + (ISLAND_H - ICON) / 2, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + ICON + gap, y, w, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, self.alttab)
        p.restore()

    def _paint_ticker(self, p, x, y, room, text, h=TICKER_H):
        """Ligne sous les mots, dans l'île : petite, centrée ; défile si elle est trop longue (#18)."""
        fm = QFontMetrics(self.font_small)
        tw = fm.horizontalAdvance(text)
        p.save()
        p.setClipRect(QRectF(x, y, room, h))
        p.setPen(QColor(255, 255, 255, 190))
        p.setFont(self.font_small)
        if tw <= room:
            p.drawText(QRectF(x, y, room, h), Qt.AlignmentFlag.AlignCenter, text)
        elif not self.motion:
            p.drawText(QRectF(x, y, room, h), Qt.AlignmentFlag.AlignCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, int(room)))
        else:
            off = ticker_offset(tw, room, getattr(self, "now", 0.0) - getattr(self, "ticker_t0", 0.0))
            p.drawText(QRectF(x + off, y, tw + 4, h), Qt.AlignmentFlag.AlignVCenter, text)
        p.restore()

    def _paint_timer_pill(self, p, x, y, text, countdown):
        """Fiche « sablier + temps » ; renvoie sa largeur."""
        fm = QFontMetrics(self.font_msg)
        pad, gap = 18, 10
        w = 2 * pad + ICON + gap + fm.horizontalAdvance(text)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(28, 38, 70, 245) if countdown else QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        icon = self.icons.get("timer")
        if icon is not None:
            icon.render(p, QRectF(x + pad, y + (ISLAND_H - ICON) / 2, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + ICON + gap, y, w, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, text)
        p.restore()
        return w

    def _paint_clock(self, p, x, y):
        """Fiche « horloge + jour, date, heure », sous l'île ; apparaît avec l'agrandissement du logo."""
        if not self.next_rem:
            return
        k, _ = clock_anim(getattr(self, "anim_now", 0.0), self.clk_start, self.clk_end, getattr(self, "motion", True))
        if k <= 0.01:
            return
        fm = QFontMetrics(self.font_msg)
        pad, gap = 18, 10
        w = 2 * pad + ICON + gap + fm.horizontalAdvance(self.next_rem)
        p.save()
        p.setOpacity(k)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(QRectF(x, y, w, ISLAND_H), ISLAND_H / 2, ISLAND_H / 2)
        clock = self.icons.get("clock")
        if clock is not None:
            clock.render(p, QRectF(x + pad, y + (ISLAND_H - ICON) / 2, ICON, ICON))
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font_msg)
        p.drawText(QRectF(x + pad + ICON + gap, y, w, ISLAND_H), Qt.AlignmentFlag.AlignVCenter, self.next_rem)
        p.restore()

    def _paint_islet(self, p, x, y):
        """Logo à sa place, ou en cours d'animation (« iris heure ») : il grossit vers la gauche en tournant
        jusqu'à couvrir l'île et la fiche de l'heure, son bord droit restant collé à l'île."""
        k, angle = clock_anim(getattr(self, "anim_now", 0.0), self.clk_start, self.clk_end, getattr(self, "motion", True))
        size = ISLET + (CLOCK_BIG - ISLET) * k
        right = x + ISLET
        bars_top = ISLAND_TOP + (ISLET - ISLAND_H) / 2
        cy = (y + ISLET / 2) + ((bars_top + CLOCK_BIG / 2) - (y + ISLET / 2)) * k
        self._paint_discord(p, right - size, y)
        p.save()
        p.translate(right - size / 2, cy)
        p.rotate(angle)
        p.scale(size / ISLET, size / ISLET)
        p.translate(-ISLET / 2, -ISLET / 2)
        self._draw_logo(p, 0, 0)
        p.restore()

    def _draw_logo(self, p, x, y):
        paint_logo(p, x, y, ISLET, self.logos.get(self.logo), self.ring)
