from qgis.core import (
    QgsGeometry, QgsPointXY, QgsCoordinateTransform, QgsProject,
    QgsWkbTypes,
)


def sample_profile(line_geom, raster_layer, interval, line_crs):
    """Sample elevation along line_geom at regular `interval` spacing.

    Distance is measured in line_crs map units so the resulting profile's
    X axis stays in the project's real-world units regardless of the
    DEM's CRS. Each sample point is reprojected into the raster's CRS only
    for the value lookup.

    Returns a list of (distance, elevation, is_valid) tuples. A gap between
    disjoint parts of a multi-part line is marked with is_valid=False so
    the profile builder can split there instead of bridging across it.
    """
    transform_to_raster = QgsCoordinateTransform(
        line_crs, raster_layer.crs(), QgsProject.instance()
    )
    provider = raster_layer.dataProvider()

    if QgsWkbTypes.isMultiType(line_geom.wkbType()):
        parts = line_geom.asGeometryCollection()
    else:
        parts = [line_geom]

    samples = []
    distance_offset = 0.0
    first_part = True

    for part in parts:
        part_length = part.length()
        if part_length <= 0:
            continue

        if not first_part:
            samples.append((distance_offset, 0.0, False))
        first_part = False

        n_steps = max(1, int(part_length // interval))
        steps = [i * interval for i in range(n_steps + 1)]
        if steps[-1] < part_length:
            steps.append(part_length)

        for d in steps:
            point = part.interpolate(d).asPoint()
            try:
                raster_point = transform_to_raster.transform(QgsPointXY(point))
                value, ok = provider.sample(raster_point, 1)
            except Exception:
                value, ok = None, False
            samples.append((distance_offset + d, value if ok else 0.0, bool(ok)))

        distance_offset += part_length

    return samples
