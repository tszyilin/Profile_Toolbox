from qgis.core import QgsGeometry, QgsSpatialIndex, QgsWkbTypes


def select_closest_line_feature(layer, point):
    """Return (geometry, crs) of the line feature in `layer` closest to
    `point` (a QgsPointXY in the layer's CRS), or (None, None) if the layer
    has no line features."""
    if layer is None or layer.geometryType() != QgsWkbTypes.LineGeometry:
        return None, None

    index = QgsSpatialIndex()
    features_by_id = {}
    for feature in layer.getFeatures():
        index.addFeature(feature)
        features_by_id[feature.id()] = feature

    nearest = index.nearestNeighbor(point, 1)
    if not nearest:
        return None, None

    point_geom = QgsGeometry.fromPointXY(point)
    best_id = min(nearest, key=lambda fid: features_by_id[fid].geometry().distance(point_geom))
    feature = features_by_id.get(best_id)
    if feature is None:
        return None, None
    return feature.geometry(), layer.crs()
