from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField,
    QgsSingleSymbolRenderer, QgsLineSymbol,
)


def build_profile_layer(samples, transform, crs_authid, layer_name='Profile Line'):
    layer = QgsVectorLayer(f'LineString?crs={crs_authid}', layer_name, 'memory')
    provider = layer.dataProvider()
    provider.addAttributes([QgsField('type', QVariant.String)])
    layer.updateFields()

    features = []
    run = []
    for distance, elevation, is_valid in samples:
        if is_valid:
            run.append(transform.to_map(distance, elevation))
        else:
            if len(run) >= 2:
                features.append(_make_feature(run))
            run = []
    if len(run) >= 2:
        features.append(_make_feature(run))

    provider.addFeatures(features)
    layer.updateExtents()
    return layer


def _make_feature(points):
    f = QgsFeature()
    f.setAttributes(['profile'])
    f.setGeometry(QgsGeometry.fromPolylineXY(points))
    return f


def apply_profile_symbology(layer):
    symbol = QgsLineSymbol.createSimple({'color': '178,34,34', 'width': '0.5'})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()
