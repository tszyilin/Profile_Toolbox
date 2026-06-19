from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import QgsGeometry, QgsWkbTypes


class DrawLineMapTool(QgsMapTool):
    """Click to add vertices to a cross-section line; right-click, Enter,
    or double-click to finish. Escape cancels."""

    def __init__(self, canvas, finished_callback, cancelled_callback=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.finished_callback = finished_callback
        self.cancelled_callback = cancelled_callback
        self.points = []
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0))
        self.rubber_band.setWidth(2)
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._finish()
            return
        point = self.toMapCoordinates(e.pos())
        self.points.append(point)
        self.rubber_band.setToGeometry(QgsGeometry.fromPolylineXY(self.points), None)

    def canvasMoveEvent(self, e):
        if not self.points:
            return
        preview = self.points + [self.toMapCoordinates(e.pos())]
        self.rubber_band.setToGeometry(QgsGeometry.fromPolylineXY(preview), None)

    def canvasDoubleClickEvent(self, e):
        if self.points:
            self.points.pop()
        self._finish()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish()

    def _finish(self):
        if len(self.points) < 2:
            self._cancel()
            return
        geom = QgsGeometry.fromPolylineXY(self.points)
        self._reset()
        self.finished_callback(geom)

    def _cancel(self):
        self._reset()
        if self.cancelled_callback:
            self.cancelled_callback()

    def _reset(self):
        self.points = []
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)

    def deactivate(self):
        self._reset()
        super().deactivate()


class PickAnchorMapTool(QgsMapTool):
    """Click a point on the canvas to use as the bottom-left anchor."""

    def __init__(self, canvas, picked_callback):
        super().__init__(canvas)
        self.canvas = canvas
        self.picked_callback = picked_callback
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        point = self.toMapCoordinates(e.pos())
        self.picked_callback(point)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.canvas.unsetMapTool(self)
