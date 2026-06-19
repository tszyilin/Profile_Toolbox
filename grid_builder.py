import math

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsLineSymbol,
)


def build_grid_layer(transform, x_dist, x_seg, y_min, y_max, y_int, crs_authid,
                      layer_name='Profile Grid'):
    if y_min >= y_max:
        raise ValueError('Y Min must be less than Y Max.')
    if x_seg <= 0 or y_int <= 0:
        raise ValueError('Segment and interval must be greater than zero.')

    layer = QgsVectorLayer(f'LineString?crs={crs_authid}', layer_name, 'memory')
    provider = layer.dataProvider()
    provider.addAttributes([QgsField('type', QVariant.String)])
    layer.updateFields()

    features = []

    border = QgsFeature()
    border.setAttributes(['border'])
    border.setGeometry(QgsGeometry.fromPolylineXY([
        transform.to_map(0, y_min),
        transform.to_map(x_dist, y_min),
        transform.to_map(x_dist, y_max),
        transform.to_map(0, y_max),
        transform.to_map(0, y_min),
    ]))
    features.append(border)

    n_x = int(math.floor(x_dist / x_seg))
    for i in range(1, n_x):
        x = i * x_seg
        f = QgsFeature()
        f.setAttributes(['grid_x'])
        f.setGeometry(QgsGeometry.fromPolylineXY([
            transform.to_map(x, y_min),
            transform.to_map(x, y_max),
        ]))
        features.append(f)

    n_y = int(math.floor((y_max - y_min) / y_int))
    for i in range(1, n_y):
        y = y_min + i * y_int
        f = QgsFeature()
        f.setAttributes(['grid_y'])
        f.setGeometry(QgsGeometry.fromPolylineXY([
            transform.to_map(0, y),
            transform.to_map(x_dist, y),
        ]))
        features.append(f)

    provider.addFeatures(features)
    layer.updateExtents()
    return layer


def apply_grid_symbology(layer):
    categories = [
        QgsRendererCategory(
            'border', QgsLineSymbol.createSimple({'color': '0,0,0', 'width': '0.6'}), 'Border'),
        QgsRendererCategory(
            'grid_x', QgsLineSymbol.createSimple(
                {'color': '150,150,150', 'width': '0.2', 'line_style': 'dash'}), 'Grid X'),
        QgsRendererCategory(
            'grid_y', QgsLineSymbol.createSimple(
                {'color': '150,150,150', 'width': '0.2', 'line_style': 'dash'}), 'Grid Y'),
    ]
    layer.setRenderer(QgsCategorizedSymbolRenderer('type', categories))
    layer.triggerRepaint()
