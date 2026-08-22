# -*- coding: utf-8 -*-
"""A sliding on/off switch.

Drop-in for a QCheckBox where a switch reads better than a tick box: it is
checkable and emits `toggled`, so `isChecked()` / `setChecked()` / `toggled`
all behave the same way.
"""

from qgis.PyQt.QtCore import QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from qgis.PyQt.QtGui import QColor, QPainter, QPalette
from qgis.PyQt.QtWidgets import QAbstractButton, QSizePolicy


class ToggleSwitch(QAbstractButton):

    TRACK_WIDTH = 40
    TRACK_HEIGHT = 20
    MARGIN = 2

    def __init__(self, parent=None, on_colour="#2d7dd2", off_colour=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        self._on_colour = QColor(on_colour)
        self._off_colour = QColor(off_colour) if off_colour else QColor("#9a9a9a")
        self._offset = 0.0

        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(120)
        self.toggled.connect(self._animate)

    # ---- the sliding knob position, 0.0 = left, 1.0 = right --------------

    @pyqtProperty(float)
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value):
        self._offset = value
        self.update()

    def _animate(self, checked):
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked):
        super().setChecked(checked)
        # Land the knob immediately when set in code rather than by clicking.
        self._offset = 1.0 if checked else 0.0
        self.update()

    # ---- painting ---------------------------------------------------------

    def sizeHint(self):
        return QSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QRectF(0, 0, self.TRACK_WIDTH, self.TRACK_HEIGHT)
        radius = track.height() / 2.0

        colour = QColor(self._on_colour if self.isChecked() else self._off_colour)
        if not self.isEnabled():
            colour.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawRoundedRect(track, radius, radius)

        diameter = self.TRACK_HEIGHT - 2 * self.MARGIN
        travel = self.TRACK_WIDTH - diameter - 2 * self.MARGIN
        knob = QRectF(
            self.MARGIN + self._offset * travel,
            self.MARGIN,
            diameter,
            diameter,
        )
        painter.setBrush(self.palette().color(QPalette.ColorRole.Base))
        painter.drawEllipse(knob)
