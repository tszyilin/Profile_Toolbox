from qgis.core import QgsProject, QgsVectorLayer, QgsFeature

LAYER_NAME = 'Cross Section Line'


class CrossSectionLineManager:
    """Keeps a single in-memory vector layer in sync with whichever line
    geometry is currently used for sampling, replacing it instead of
    accumulating duplicates each time the line changes."""

    def __init__(self):
        self._layer = None

    def ensure_layer(self, geom, crs_authid):
        project = QgsProject.instance()
        if self._layer is not None and project.mapLayer(self._layer.id()) is not None:
            project.removeMapLayer(self._layer.id())
        self._layer = None

        layer = QgsVectorLayer(f'LineString?crs={crs_authid}', LAYER_NAME, 'memory')
        feature = QgsFeature()
        feature.setGeometry(geom)
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        project.addMapLayer(layer)
        self._layer = layer
        return layer
