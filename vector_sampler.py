from qgis.core import QgsCoordinateTransform, QgsFeatureRequest, QgsGeometry, QgsProject


def sample_profile_vector(line_geom, point_layer, field_name, buffer_distance, line_crs):
    """Sample a numeric field from point features within `buffer_distance` of
    `line_geom`, projecting each point onto the line to get its distance.

    Returns a list of (distance, value, is_valid) tuples sorted by distance,
    matching the raster sampler's output shape so the chart/table can treat
    both kinds of series identically.
    """
    transform_to_layer = QgsCoordinateTransform(line_crs, point_layer.crs(), QgsProject.instance())
    transform_to_line = QgsCoordinateTransform(point_layer.crs(), line_crs, QgsProject.instance())

    line_in_layer_crs = QgsGeometry(line_geom)
    line_in_layer_crs.transform(transform_to_layer)
    search_rect = line_in_layer_crs.buffer(buffer_distance, 8).boundingBox()

    field_idx = point_layer.fields().indexFromName(field_name)
    samples = []
    for feature in point_layer.getFeatures(QgsFeatureRequest().setFilterRect(search_rect)):
        point_geom = feature.geometry()
        if point_geom.isEmpty():
            continue
        point_in_line_crs = transform_to_line.transform(point_geom.asPoint())
        point_geom_in_line_crs = QgsGeometry.fromPointXY(point_in_line_crs)
        if line_geom.distance(point_geom_in_line_crs) > buffer_distance:
            continue
        try:
            value = float(feature[field_idx])
        except (TypeError, ValueError):
            continue
        distance = line_geom.lineLocatePoint(point_geom_in_line_crs)
        samples.append((distance, value, True))

    samples.sort(key=lambda s: s[0])
    return samples
