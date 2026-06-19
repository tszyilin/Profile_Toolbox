from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QDoubleSpinBox, QPushButton, QCheckBox, QLabel, QMessageBox,
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature,
    QgsMapLayerProxyModel,
)
from qgis.gui import QgsMapLayerComboBox

from .map_tools import DrawLineMapTool, PickAnchorMapTool
from .raster_sampler import sample_profile
from .geom_transform import ProfileTransform
from .grid_builder import build_grid_layer, apply_grid_symbology
from .profile_layer_builder import build_profile_layer, apply_profile_symbology

MAX_SAMPLE_COUNT = 8000


class ProfileToolDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.setWindowTitle('Create Profile Plot')

        self.line_geom = None
        self.line_crs = None
        self.samples = None
        self.draw_tool = None
        self.pick_tool = None
        self._previous_map_tool = None

        self._build_ui()

    # ---- UI ----------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Line source
        layout.addWidget(QLabel('<b>1. Cross-section line</b>'))
        line_row = QHBoxLayout()
        self.line_layer_combo = QgsMapLayerComboBox()
        self.line_layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        line_row.addWidget(self.line_layer_combo)
        draw_btn = QPushButton('Draw New Line')
        draw_btn.clicked.connect(self._activate_draw_tool)
        line_row.addWidget(draw_btn)
        layout.addLayout(line_row)

        self.line_status_label = QLabel('No line drawn yet.')
        layout.addWidget(self.line_status_label)

        self.save_line_btn = QPushButton('Save Drawn Line as Layer')
        self.save_line_btn.setEnabled(False)
        self.save_line_btn.clicked.connect(self._save_drawn_line_layer)
        layout.addWidget(self.save_line_btn)

        # DEM sampling
        layout.addWidget(QLabel('<b>2. Sample elevation (DEM)</b>'))
        dem_form = QFormLayout()
        self.raster_combo = QgsMapLayerComboBox()
        self.raster_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        dem_form.addRow('DEM layer:', self.raster_combo)

        self.sample_interval = QDoubleSpinBox()
        self.sample_interval.setRange(0.01, 100_000)
        self.sample_interval.setDecimals(2)
        self.sample_interval.setValue(10)
        self.sample_interval.setSuffix(' m')
        dem_form.addRow('Sample interval:', self.sample_interval)
        layout.addLayout(dem_form)

        sample_btn = QPushButton('Sample Elevation')
        sample_btn.clicked.connect(self._sample_elevation)
        layout.addWidget(sample_btn)

        self.sample_status_label = QLabel('No samples yet.')
        layout.addWidget(self.sample_status_label)

        # Vertical scale / grid params
        layout.addWidget(QLabel('<b>3. Grid &amp; vertical scale</b>'))
        form = QFormLayout()

        self.x_segment = QDoubleSpinBox()
        self.x_segment.setRange(0.1, 100_000)
        self.x_segment.setDecimals(1)
        self.x_segment.setValue(100)
        self.x_segment.setSuffix(' m')
        form.addRow('Grid X interval:', self.x_segment)

        self.y_min = QDoubleSpinBox()
        self.y_min.setRange(-10_000, 10_000)
        self.y_min.setDecimals(1)
        self.y_min.setSuffix(' m RL')
        form.addRow('Y Min (RL):', self.y_min)

        self.y_max = QDoubleSpinBox()
        self.y_max.setRange(-10_000, 10_000)
        self.y_max.setDecimals(1)
        self.y_max.setSuffix(' m RL')
        form.addRow('Y Max (RL):', self.y_max)

        self.y_interval = QDoubleSpinBox()
        self.y_interval.setRange(0.1, 10_000)
        self.y_interval.setDecimals(1)
        self.y_interval.setValue(2)
        self.y_interval.setSuffix(' m')
        form.addRow('Y Interval:', self.y_interval)

        self.exaggeration = QDoubleSpinBox()
        self.exaggeration.setRange(0.1, 1000)
        self.exaggeration.setDecimals(1)
        self.exaggeration.setValue(5)
        self.exaggeration.setSuffix(' x')
        form.addRow('Vertical exaggeration:', self.exaggeration)

        self.true_scale_check = QCheckBox('1:1 true scale')
        self.true_scale_check.toggled.connect(self.exaggeration.setDisabled)
        form.addRow('', self.true_scale_check)

        layout.addLayout(form)

        # Plot
        layout.addWidget(QLabel('<b>4. Plot</b>'))
        self.plot_btn = QPushButton('Plot Profile (click map to place)')
        self.plot_btn.setEnabled(False)
        self.plot_btn.clicked.connect(self._activate_pick_tool)
        layout.addWidget(self.plot_btn)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    # ---- Line drawing --------------------------------------------------

    def _activate_draw_tool(self):
        self._previous_map_tool = self.canvas.mapTool()
        self.draw_tool = DrawLineMapTool(self.canvas, self._on_line_drawn, self._restore_map_tool)
        self.canvas.setMapTool(self.draw_tool)

    def _on_line_drawn(self, geom):
        self.line_geom = geom
        self.line_crs = QgsProject.instance().crs()
        length = geom.length()
        self.line_status_label.setText(f'Drawn line: {length:.1f} m, {geom.constGet().nCoordinates()} vertices.')
        self.save_line_btn.setEnabled(True)
        self._restore_map_tool()

    def _restore_map_tool(self):
        self.canvas.setMapTool(self._previous_map_tool)

    def _save_drawn_line_layer(self):
        if self.line_geom is None:
            return
        crs = QgsProject.instance().crs().authid()
        layer = QgsVectorLayer(f'LineString?crs={crs}', 'Cross Section Line', 'memory')
        feature = QgsFeature()
        feature.setGeometry(self.line_geom)
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

    def _get_selected_line_geometry(self):
        layer = self.line_layer_combo.currentLayer()
        if layer is None:
            return None, None
        selected = layer.selectedFeatures()
        feature = selected[0] if selected else next(layer.getFeatures(), None)
        if feature is None:
            return None, None
        return feature.geometry(), layer.crs()

    # ---- DEM sampling ---------------------------------------------------

    def _sample_elevation(self):
        geom, crs = self.line_geom, self.line_crs
        if geom is None:
            geom, crs = self._get_selected_line_geometry()

        if geom is None:
            QMessageBox.warning(self, 'No Line', 'Draw a line or select a line layer with a feature first.')
            return

        raster_layer = self.raster_combo.currentLayer()
        if raster_layer is None:
            QMessageBox.warning(self, 'No DEM', 'Select a raster layer to sample elevation from.')
            return

        interval = self.sample_interval.value()
        length = geom.length()
        if length <= 0:
            QMessageBox.warning(self, 'Invalid Line', 'The selected line has zero length.')
            return

        estimated_count = int(length / interval) + 1
        if estimated_count > MAX_SAMPLE_COUNT:
            reply = QMessageBox.question(
                self, 'Large Sample Count',
                f'This will take about {estimated_count} samples, which may be slow. Continue?',
            )
            if reply != QMessageBox.Yes:
                return

        self.line_geom = geom
        self.line_crs = crs
        self.samples = sample_profile(geom, raster_layer, interval, crs)

        valid = [s for s in self.samples if s[2]]
        n_gaps = sum(1 for s in self.samples if not s[2])
        if not valid:
            QMessageBox.warning(self, 'No Data', 'No valid elevation samples were found along this line.')
            self.plot_btn.setEnabled(False)
            return

        elevations = [e for _, e, _ in valid]
        self.y_min.setValue(min(elevations) - 5)
        self.y_max.setValue(max(elevations) + 5)

        self.sample_status_label.setText(
            f'{len(self.samples)} samples, {n_gaps} nodata gap(s).'
        )
        self.plot_btn.setEnabled(True)

    # ---- Plot / anchor ---------------------------------------------------

    def _activate_pick_tool(self):
        if not self.samples:
            return
        self._previous_map_tool = self.canvas.mapTool()
        self.pick_tool = PickAnchorMapTool(self.canvas, self._on_anchor_picked)
        self.canvas.setMapTool(self.pick_tool)

    def _on_anchor_picked(self, point):
        self._restore_map_tool()

        y_min = self.y_min.value()
        y_max = self.y_max.value()
        if y_min >= y_max:
            QMessageBox.warning(self, 'Invalid Input', 'Y Min must be less than Y Max.')
            return

        y_scale = 1.0 if self.true_scale_check.isChecked() else self.exaggeration.value()
        transform = ProfileTransform(anchor=point, x_scale=1.0, y_scale=y_scale, y_base=y_min)

        x_dist = self.samples[-1][0]
        crs_authid = QgsProject.instance().crs().authid()

        try:
            grid_layer = build_grid_layer(
                transform, x_dist, self.x_segment.value(),
                y_min, y_max, self.y_interval.value(), crs_authid,
            )
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid Input', str(exc))
            return

        apply_grid_symbology(grid_layer)
        QgsProject.instance().addMapLayer(grid_layer)

        profile_layer = build_profile_layer(self.samples, transform, crs_authid)
        apply_profile_symbology(profile_layer)
        QgsProject.instance().addMapLayer(profile_layer)

        out_of_range = any(e < y_min or e > y_max for _, e, ok in self.samples if ok)

        extent = grid_layer.extent()
        extent.combineExtentWith(profile_layer.extent())
        self.canvas.setExtent(extent)
        self.canvas.refresh()

        message = 'Profile plotted.'
        if out_of_range:
            message += ' Note: some elevations fall outside the Y Min/Max range.'
        self.iface.messageBar().pushSuccess('Profile Plot', message)

    # ---- Cleanup ---------------------------------------------------------

    def closeEvent(self, event):
        if self.canvas.mapTool() in (self.draw_tool, self.pick_tool):
            self.canvas.unsetMapTool(self.canvas.mapTool())
        super().closeEvent(event)
