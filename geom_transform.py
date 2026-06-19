from qgis.core import QgsPointXY


class ProfileTransform:
    """Maps (distance, elevation) profile-space coordinates to map coordinates,
    anchored at a picked map point with independent X/Y scale factors."""

    def __init__(self, anchor: QgsPointXY, x_scale: float, y_scale: float, y_base: float):
        self.anchor = anchor
        self.x_scale = x_scale
        self.y_scale = y_scale
        self.y_base = y_base

    def to_map(self, distance: float, elevation: float) -> QgsPointXY:
        x = self.anchor.x() + distance * self.x_scale
        y = self.anchor.y() + (elevation - self.y_base) * self.y_scale
        return QgsPointXY(x, y)
