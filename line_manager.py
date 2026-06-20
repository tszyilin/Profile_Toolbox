from qgis.PyQt.QtGui import QColor
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject, QgsWkbTypes
from qgis.gui import QgsRubberBand


class CrossSectionLineManager:
    """Shows the current cross-section line on the map canvas as a rubber
    band, so it never appears as a layer in the Layers panel."""

    def __init__(self, canvas):
        self.canvas = canvas
        self._rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber_band.setColor(QColor(255, 0, 0))
        self._rubber_band.setWidth(2)

    def update(self, geom, crs_authid):
        dest_crs = self.canvas.mapSettings().destinationCrs()
        src_crs = QgsCoordinateReferenceSystem(crs_authid)
        display_geom = QgsGeometry(geom)
        if src_crs.isValid() and src_crs != dest_crs:
            transform = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())
            display_geom.transform(transform)
        self._rubber_band.setToGeometry(display_geom, None)

    def reset(self):
        self._rubber_band.reset(QgsWkbTypes.LineGeometry)
