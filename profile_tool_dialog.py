from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QCheckBox, QLabel, QLineEdit,
    QComboBox, QMessageBox, QTabWidget, QWidget, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QFileDialog, QColorDialog,
    QApplication,
)
from qgis.core import (
    QgsProject, QgsMapLayerProxyModel, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsGeometry, QgsFeature, QgsField,
)
from qgis.gui import QgsMapLayerComboBox, QgsRubberBand

from .map_tools import DrawLineMapTool, PickAnchorMapTool, SelectLineMapTool
from .raster_sampler import sample_profile
from .vector_sampler import sample_profile_vector
from .geom_transform import ProfileTransform
from .grid_builder import build_grid_layer, apply_grid_symbology
from .profile_layer_builder import build_profile_layer, apply_profile_symbology
from .line_manager import CrossSectionLineManager
from .chart_widget import ProfileChartWidget

MAX_SAMPLE_COUNT = 8000
DEFAULT_SERIES_COLORS = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]


class ProfileToolDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.setWindowTitle('Profile Tool')

        self.line_geom = None
        self.line_crs = None
        self.samples = None
        self._series = []
        self.draw_tool = None
        self.pick_tool = None
        self.select_tool = None
        self._previous_map_tool = None
        self.line_manager = CrossSectionLineManager()

        self._last_hover_x = None
        self._hover_marker = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
        self._hover_marker.setColor(QColor(255, 0, 0))
        self._hover_marker.setIcon(QgsRubberBand.ICON_CIRCLE)
        self._hover_marker.setIconSize(8)
        self._hover_marker.reset(QgsWkbTypes.PointGeometry)

        self._build_ui()

    # ---- UI ----------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_profile_tab(), 'Profile')
        self.tabs.addTab(self._build_table_tab(), 'Table')
        self.tabs.addTab(self._build_settings_tab(), 'Settings')

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _build_profile_tab(self):
        tab = QWidget()
        outer = QHBoxLayout(tab)

        # ---- left: chart + Y range + toolbar + crosshair readout ----
        left = QVBoxLayout()
        self.chart = ProfileChartWidget()
        self.chart.mouse_move_callback = self._on_chart_mouse_move

        chart_row = QHBoxLayout()
        chart_row.addWidget(self.chart, stretch=1)

        y_range_col = QVBoxLayout()
        y_range_col.addWidget(QLabel('maximum'))
        self.chart_y_max = QDoubleSpinBox()
        self.chart_y_max.setRange(-100_000, 100_000)
        self.chart_y_max.setDecimals(1)
        self.chart_y_max.setMaximumWidth(80)
        self.chart_y_max.valueChanged.connect(self._on_chart_range_changed)
        y_range_col.addWidget(self.chart_y_max)
        y_range_col.addStretch(1)
        y_range_col.addWidget(QLabel('minimum'))
        self.chart_y_min = QDoubleSpinBox()
        self.chart_y_min.setRange(-100_000, 100_000)
        self.chart_y_min.setDecimals(1)
        self.chart_y_min.setMaximumWidth(80)
        self.chart_y_min.valueChanged.connect(self._on_chart_range_changed)
        y_range_col.addWidget(self.chart_y_min)
        chart_row.addLayout(y_range_col)

        left.addLayout(chart_row, stretch=1)

        toolbar_row = QHBoxLayout()
        reset_btn = QPushButton('Reset view')
        reset_btn.clicked.connect(self.chart.reset_view)
        toolbar_row.addWidget(reset_btn)

        toolbar_row.addWidget(QLabel('Y axis:'))
        self.y_field_combo = QComboBox()
        self.y_field_combo.addItem('Height')
        toolbar_row.addWidget(self.y_field_combo)

        self.interp_check = QCheckBox('Interpolated profile')
        self.interp_check.setChecked(True)
        self.interp_check.toggled.connect(self._update_chart)
        toolbar_row.addWidget(self.interp_check)

        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(['Graph - PNG', 'Graph - SVG', 'Graph - PDF'])
        toolbar_row.addWidget(self.export_format_combo)

        save_as_btn = QPushButton('Save as')
        save_as_btn.clicked.connect(self._on_save_chart_image)
        toolbar_row.addWidget(save_as_btn)
        left.addLayout(toolbar_row)

        readout_row = QHBoxLayout()
        readout_row.addWidget(QLabel('X:'))
        self.x_readout = QLineEdit('/')
        self.x_readout.setReadOnly(True)
        readout_row.addWidget(self.x_readout)
        readout_row.addWidget(QLabel('Y:'))
        self.y_readout = QLineEdit('/')
        self.y_readout.setReadOnly(True)
        readout_row.addWidget(self.y_readout)
        left.addLayout(readout_row)

        outer.addLayout(left, stretch=3)

        # ---- right: source, DEM layers, options ----
        right = QVBoxLayout()

        source_box = QGroupBox('Source')
        source_layout = QVBoxLayout(source_box)
        self.line_layer_combo = QgsMapLayerComboBox()
        self.line_layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        source_layout.addWidget(self.line_layer_combo)
        self.line_status_label = QLabel('No line drawn yet.')
        source_layout.addWidget(self.line_status_label)
        sample_btn = QPushButton('Sample Elevation')
        sample_btn.clicked.connect(self._sample_elevation)
        source_layout.addWidget(sample_btn)
        self.sample_status_label = QLabel('No samples yet.')
        source_layout.addWidget(self.sample_status_label)
        right.addWidget(source_box)

        dem_box = QGroupBox('DEM layers')
        dem_layout = QVBoxLayout(dem_box)
        dem_picker_row = QHBoxLayout()
        self.dem_picker_combo = QgsMapLayerComboBox()
        self.dem_picker_combo.setFilters(QgsMapLayerProxyModel.RasterLayer | QgsMapLayerProxyModel.PointLayer)
        dem_picker_row.addWidget(self.dem_picker_combo)
        self.add_dem_btn = QPushButton('Add Layer')
        self.add_dem_btn.clicked.connect(self._on_add_dem_layer)
        dem_picker_row.addWidget(self.add_dem_btn)
        dem_layout.addLayout(dem_picker_row)

        self.dem_table = QTableWidget(0, 5)
        self.dem_table.setHorizontalHeaderLabels(['', 'Color', 'Layer', 'Band/Field', 'Buffer (m)'])
        self.dem_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.dem_table.cellClicked.connect(self._on_dem_table_cell_clicked)
        dem_layout.addWidget(self.dem_table)

        self.remove_dem_btn = QPushButton('Remove Layer')
        self.remove_dem_btn.clicked.connect(self._on_remove_dem_layer)
        dem_layout.addWidget(self.remove_dem_btn)
        right.addWidget(dem_box)

        options_box = QGroupBox('Options')
        options_form = QFormLayout(options_box)
        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItems(
            ['Temporary polyline', 'Selected polyline', 'Selected layer', 'Create polyline']
        )
        self.selection_mode_combo.activated.connect(self._on_selection_mode_activated)
        options_form.addRow('Selection', self.selection_mode_combo)
        self.show_cursor_check = QCheckBox('Show cursor')
        self.show_cursor_check.setChecked(True)
        options_form.addRow('', self.show_cursor_check)
        self.link_canvas_check = QCheckBox('Link mouse position on graph with canvas')
        self.link_canvas_check.toggled.connect(
            lambda checked: self._update_hover_marker(self._last_hover_x if checked else None)
        )
        options_form.addRow('', self.link_canvas_check)
        right.addWidget(options_box)

        right.addStretch(1)
        outer.addLayout(right, stretch=1)

        return tab

    def _build_table_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.samples_table = QTableWidget(0, 3)
        self.samples_table.setHorizontalHeaderLabels(['Distance (m)', 'Elevation', 'Valid'])
        layout.addWidget(self.samples_table)

        button_row = QHBoxLayout()
        self.copy_table_btn = QPushButton('Copy to clipboard')
        self.copy_table_btn.clicked.connect(self._on_copy_table)
        button_row.addWidget(self.copy_table_btn)

        self.copy_table_coords_btn = QPushButton('Copy to clipboard (with coordinates)')
        self.copy_table_coords_btn.clicked.connect(self._on_copy_table_with_coords)
        button_row.addWidget(self.copy_table_coords_btn)

        self.create_layer_btn = QPushButton('Create Temporary layer')
        self.create_layer_btn.clicked.connect(self._on_create_temp_layer)
        button_row.addWidget(self.create_layer_btn)
        layout.addLayout(button_row)

        return tab

    def _build_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        sampling_box = QGroupBox('Sampling')
        sampling_form = QFormLayout(sampling_box)
        self.sample_interval = QDoubleSpinBox()
        self.sample_interval.setRange(0.01, 100_000)
        self.sample_interval.setDecimals(2)
        self.sample_interval.setValue(10)
        self.sample_interval.setSuffix(' m')
        sampling_form.addRow('Sample interval:', self.sample_interval)
        self.live_update_check = QCheckBox('Live update while drawing')
        sampling_form.addRow('', self.live_update_check)
        layout.addWidget(sampling_box)

        grid_box = QGroupBox('Grid / vertical scale')
        form = QFormLayout(grid_box)

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

        layout.addWidget(grid_box)

        export_box = QGroupBox('Map export')
        export_layout = QVBoxLayout(export_box)
        self.export_to_map_btn = QPushButton('Export Profile to Map (grid + line)...')
        self.export_to_map_btn.setEnabled(False)
        self.export_to_map_btn.clicked.connect(self._on_export_to_map)
        export_layout.addWidget(self.export_to_map_btn)
        layout.addWidget(export_box)

        layout.addStretch(1)
        return tab

    # ---- Line drawing --------------------------------------------------

    def _activate_draw_tool(self):
        self._previous_map_tool = self.canvas.mapTool()
        self.draw_tool = DrawLineMapTool(
            self.canvas, self._on_line_drawn, self._restore_map_tool,
            point_added_callback=self._on_draw_point_added,
        )
        self.canvas.setMapTool(self.draw_tool)

    def _on_draw_point_added(self, points):
        if not self.live_update_check.isChecked() or len(points) < 2:
            return
        geom = QgsGeometry.fromPolylineXY(points)
        self._live_resample(geom, QgsProject.instance().crs())

    def _activate_select_tool(self):
        self._previous_map_tool = self.canvas.mapTool()
        self.select_tool = SelectLineMapTool(
            self.canvas, self._get_select_target_layer, self._on_line_selected, self._restore_map_tool,
        )
        self.canvas.setMapTool(self.select_tool)

    def _get_select_target_layer(self):
        active = self.iface.activeLayer()
        if (
            isinstance(active, QgsVectorLayer)
            and active.geometryType() == QgsWkbTypes.LineGeometry
        ):
            return active
        return self.line_layer_combo.currentLayer()

    def _on_line_selected(self, geom, crs):
        self.line_geom = geom
        self.line_crs = crs
        self.line_status_label.setText(f'Selected line: {geom.length():.1f} m.')

    def _on_line_drawn(self, geom):
        self.line_geom = geom
        self.line_crs = QgsProject.instance().crs()
        length = geom.length()
        self.line_status_label.setText(f'Drawn line: {length:.1f} m, {geom.constGet().nCoordinates()} vertices.')
        self.selection_mode_combo.setCurrentText('Temporary polyline')
        self._restore_map_tool()

    def _restore_map_tool(self):
        self.canvas.setMapTool(self._previous_map_tool)

    def _on_selection_mode_activated(self, index):
        text = self.selection_mode_combo.itemText(index)
        if text == 'Create polyline':
            self._activate_draw_tool()
        elif text == 'Selected polyline':
            self._activate_select_tool()

    def _get_layer_combo_line_geometry(self):
        layer = self.line_layer_combo.currentLayer()
        if layer is None:
            return None, None
        selected = layer.selectedFeatures()
        feature = selected[0] if selected else next(layer.getFeatures(), None)
        if feature is None:
            return None, None
        return feature.geometry(), layer.crs()

    def _get_any_selected_line_geometry(self):
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.geometryType() != QgsWkbTypes.LineGeometry:
                continue
            selected = layer.selectedFeatures()
            if selected:
                return selected[0].geometry(), layer.crs()
        return None, None

    def _resolve_line_geometry(self):
        mode = self.selection_mode_combo.currentText()
        if mode == 'Selected layer':
            return self._get_layer_combo_line_geometry()
        if mode == 'Selected polyline' and self.line_geom is None:
            return self._get_any_selected_line_geometry()
        # 'Temporary polyline', 'Create polyline', and 'Selected polyline'
        # (once a feature has been click-selected) all use the last
        # resolved line geometry.
        return self.line_geom, self.line_crs

    # ---- DEM table -------------------------------------------------------

    def _on_add_dem_layer(self):
        layer = self.dem_picker_combo.currentLayer()
        if layer is None:
            QMessageBox.warning(self, 'No DEM', 'Select a raster or point layer to add.')
            return
        for row in range(self.dem_table.rowCount()):
            existing, _kind = self.dem_table.item(row, 2).data(Qt.UserRole)
            if existing is not None and existing.id() == layer.id():
                return

        if isinstance(layer, QgsVectorLayer):
            kind = 'vector'
            numeric_fields = [f.name() for f in layer.fields() if f.isNumeric()]
            if not numeric_fields:
                QMessageBox.warning(self, 'No Numeric Field', f'{layer.name()} has no numeric field to sample.')
                return
        else:
            kind = 'raster'

        row = self.dem_table.rowCount()
        self.dem_table.insertRow(row)

        check_item = QTableWidgetItem()
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        check_item.setCheckState(Qt.Checked)
        self.dem_table.setItem(row, 0, check_item)

        color = QColor(DEFAULT_SERIES_COLORS[row % len(DEFAULT_SERIES_COLORS)])
        color_item = QTableWidgetItem()
        color_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        color_item.setBackground(color)
        color_item.setData(Qt.UserRole, color)
        self.dem_table.setItem(row, 1, color_item)

        name_item = QTableWidgetItem(layer.name())
        name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        name_item.setData(Qt.UserRole, (layer, kind))
        self.dem_table.setItem(row, 2, name_item)

        if kind == 'raster':
            band_spin = QSpinBox()
            band_spin.setRange(1, max(1, layer.bandCount()))
            band_spin.setValue(1)
            self.dem_table.setCellWidget(row, 3, band_spin)
            buffer_spin = QDoubleSpinBox()
            buffer_spin.setEnabled(False)
            self.dem_table.setCellWidget(row, 4, buffer_spin)
        else:
            field_combo = QComboBox()
            field_combo.addItems(numeric_fields)
            self.dem_table.setCellWidget(row, 3, field_combo)
            buffer_spin = QDoubleSpinBox()
            buffer_spin.setRange(0.01, 100_000)
            buffer_spin.setDecimals(2)
            buffer_spin.setValue(5)
            buffer_spin.setSuffix(' m')
            self.dem_table.setCellWidget(row, 4, buffer_spin)

    def _on_remove_dem_layer(self):
        rows = sorted({idx.row() for idx in self.dem_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.dem_table.removeRow(row)

    def _on_dem_table_cell_clicked(self, row, column):
        if column != 1:
            return
        color_item = self.dem_table.item(row, 1)
        current_color = color_item.data(Qt.UserRole) or QColor(255, 0, 0)
        color = QColorDialog.getColor(current_color, self, 'Choose Series Color')
        if not color.isValid():
            return
        color_item.setBackground(color)
        color_item.setData(Qt.UserRole, color)

    def _checked_dem_rows(self):
        for row in range(self.dem_table.rowCount()):
            check_item = self.dem_table.item(row, 0)
            if check_item.checkState() != Qt.Checked:
                continue
            layer, kind = self.dem_table.item(row, 2).data(Qt.UserRole)
            if layer is None or not layer.isValid():
                continue
            color = self.dem_table.item(row, 1).data(Qt.UserRole)
            color = color.name() if color is not None else None
            field_widget = self.dem_table.cellWidget(row, 3)
            param = field_widget.value() if kind == 'raster' else field_widget.currentText()
            buffer = self.dem_table.cellWidget(row, 4).value()
            yield layer, kind, param, color, buffer

    # ---- DEM sampling ---------------------------------------------------

    def _sample_elevation(self):
        geom, crs = self._resolve_line_geometry()

        if geom is None:
            QMessageBox.warning(self, 'No Line', 'Draw a line, select a feature, or pick a line layer first.')
            return

        checked = list(self._checked_dem_rows())
        if not checked:
            QMessageBox.warning(self, 'No DEM', 'Check at least one DEM layer in the table to sample elevation from.')
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
        self.line_manager.ensure_layer(geom, crs.authid())

        self._series = []
        for layer, kind, param, color, buffer in checked:
            if kind == 'raster':
                if param > layer.bandCount():
                    QMessageBox.warning(
                        self, 'Invalid Band',
                        f'{layer.name()}: band {param} exceeds available bands ({layer.bandCount()}).',
                    )
                    continue
                samples = sample_profile(geom, layer, interval, crs, band=param)
            else:
                samples = sample_profile_vector(geom, layer, param, buffer, crs)
            self._series.append((layer.name(), samples, color))

        if not self._series:
            QMessageBox.warning(self, 'No Data', 'No DEM layers could be sampled (check band settings).')
            self.export_to_map_btn.setEnabled(False)
            return

        self.samples = self._series[0][1]

        valid = [s for s in self.samples if s[2]]
        n_gaps = sum(1 for s in self.samples if not s[2])
        if not valid:
            QMessageBox.warning(self, 'No Data', 'No valid elevation samples were found along this line.')
            self.export_to_map_btn.setEnabled(False)
            return

        elevations = [e for _, e, _ in valid]
        self.y_min.setValue(min(elevations) - 5)
        self.y_max.setValue(max(elevations) + 5)

        self.sample_status_label.setText(
            f'{len(checked)} DEM(s) sampled, {len(self.samples)} samples on first layer, {n_gaps} gap(s).'
        )
        self.export_to_map_btn.setEnabled(True)

        self._sync_chart_range_from_settings()
        self._update_chart()
        self._populate_samples_table()

    # ---- Profile chart ---------------------------------------------------

    def _sync_chart_range_from_settings(self):
        self.chart_y_min.setValue(self.y_min.value())
        self.chart_y_max.setValue(self.y_max.value())

    def _update_chart(self):
        if not self._series:
            return
        self.chart.set_data(self._series, interpolated=self.interp_check.isChecked())
        self.chart.set_y_range(self.chart_y_min.value(), self.chart_y_max.value())

    def _live_resample(self, geom, crs):
        checked = list(self._checked_dem_rows())
        if not checked or geom.length() <= 0:
            return
        interval = self.sample_interval.value()
        if int(geom.length() / interval) + 1 > MAX_SAMPLE_COUNT:
            return

        series = []
        for layer, kind, param, color, buffer in checked:
            if kind == 'raster':
                if param > layer.bandCount():
                    continue
                samples = sample_profile(geom, layer, interval, crs, band=param)
            else:
                samples = sample_profile_vector(geom, layer, param, buffer, crs)
            series.append((layer.name(), samples, color))

        if not series:
            return
        self._series = series
        self.samples = series[0][1]
        self.chart.set_data(self._series, interpolated=self.interp_check.isChecked())

    def _on_chart_range_changed(self, _value):
        self.chart.set_y_range(self.chart_y_min.value(), self.chart_y_max.value())

    def _on_chart_mouse_move(self, x, y):
        self._last_hover_x = x
        if x is None or y is None or not self.show_cursor_check.isChecked():
            self.x_readout.setText('/')
            self.y_readout.setText('/')
        else:
            self.x_readout.setText(f'{x:.2f}')
            self.y_readout.setText(f'{y:.2f}')
        self._update_hover_marker(x)

    def _update_hover_marker(self, distance):
        if not self.link_canvas_check.isChecked() or distance is None or self.line_geom is None:
            self._hover_marker.reset(QgsWkbTypes.PointGeometry)
            return
        length = self.line_geom.length()
        clamped = max(0.0, min(distance, length))
        point_geom = self.line_geom.interpolate(clamped)
        if point_geom.isEmpty():
            self._hover_marker.reset(QgsWkbTypes.PointGeometry)
            return
        try:
            dest_crs = self.canvas.mapSettings().destinationCrs()
            transform = QgsCoordinateTransform(self.line_crs, dest_crs, QgsProject.instance())
            map_point = transform.transform(point_geom.asPoint())
            self._hover_marker.setToGeometry(QgsGeometry.fromPointXY(map_point), None)
        except Exception:
            self._hover_marker.reset(QgsWkbTypes.PointGeometry)

    def _on_save_chart_image(self):
        fmt_label = self.export_format_combo.currentText()
        fmt = fmt_label.split('-')[-1].strip().lower()
        path, _ = QFileDialog.getSaveFileName(self, 'Save Chart', f'profile.{fmt}', f'{fmt.upper()} (*.{fmt})')
        if not path:
            return
        self.chart.save_figure(path, fmt)

    # ---- Table tab ---------------------------------------------------------

    def _populate_samples_table(self):
        table = self.samples_table
        table.setRowCount(len(self.samples))
        table.setUpdatesEnabled(False)
        for row, (distance, elevation, is_valid) in enumerate(self.samples):
            table.setItem(row, 0, QTableWidgetItem(f'{distance:.2f}'))
            table.setItem(row, 1, QTableWidgetItem(f'{elevation:.2f}' if is_valid else ''))
            table.setItem(row, 2, QTableWidgetItem('yes' if is_valid else 'no'))
        table.setUpdatesEnabled(True)

    def _on_copy_table(self):
        if not self.samples:
            return
        text = '\n'.join(f'{d}\t{e}' for d, e, ok in self.samples if ok)
        QApplication.clipboard().setText(text)

    def _on_copy_table_with_coords(self):
        if not self.samples or self.line_geom is None:
            return
        lines = []
        for d, e, ok in self.samples:
            if not ok:
                continue
            point = self.line_geom.interpolate(d).asPoint()
            lines.append(f'{d}\t{point.x()}\t{point.y()}\t{e}')
        QApplication.clipboard().setText('\n'.join(lines))

    def _on_create_temp_layer(self):
        if not self.samples or self.line_geom is None:
            QMessageBox.warning(self, 'No Data', 'Sample elevation along a line first.')
            return
        crs_authid = self.line_crs.authid() if self.line_crs else QgsProject.instance().crs().authid()
        layer = QgsVectorLayer(f'Point?crs={crs_authid}', 'ProfileTool_Points', 'memory')
        provider = layer.dataProvider()
        provider.addAttributes([QgsField('Value', QVariant.Double)])
        layer.updateFields()

        features = []
        for d, e, ok in self.samples:
            if not ok:
                continue
            point = self.line_geom.interpolate(d).asPoint()
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(point))
            feature.setAttributes([e])
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

    # ---- Export to map ---------------------------------------------------

    def _on_export_to_map(self):
        if not self.samples:
            return
        self._previous_map_tool = self.canvas.mapTool()
        self.pick_tool = PickAnchorMapTool(self.canvas, self._on_export_anchor_picked)
        self.canvas.setMapTool(self.pick_tool)

    def _on_export_anchor_picked(self, point):
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

        message = 'Profile exported to map.'
        if out_of_range:
            message += ' Note: some elevations fall outside the Y Min/Max range.'
        self.iface.messageBar().pushSuccess('Profile Plot', message)

    # ---- Cleanup ---------------------------------------------------------

    def closeEvent(self, event):
        if self.canvas.mapTool() in (self.draw_tool, self.pick_tool, self.select_tool):
            self.canvas.unsetMapTool(self.canvas.mapTool())
        self._hover_marker.reset(QgsWkbTypes.PointGeometry)
        super().closeEvent(event)
