from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QCheckBox, QLabel, QLineEdit,
    QComboBox, QMessageBox, QTabWidget, QWidget, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QFileDialog, QColorDialog,
    QApplication, QScrollArea,
)
from qgis.core import (
    QgsProject, QgsMapLayerProxyModel, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsGeometry, QgsFeature, QgsField,
)
from qgis.gui import QgsMapLayerComboBox, QgsRubberBand

from .map_tools import DrawLineMapTool, PickAnchorMapTool
from .raster_sampler import sample_profile
from .vector_sampler import sample_profile_vector
from .geom_transform import ProfileTransform
from .grid_builder import build_grid_layer, apply_grid_symbology
from .profile_layer_builder import build_profile_layer, apply_profile_symbology
from .line_manager import CrossSectionLineManager
from .chart_widget import ProfileChartWidget
from .profilers import PROFILE_TYPES

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
        self._previous_map_tool = None
        self.line_manager = CrossSectionLineManager(self.canvas)
        self._connected_layers = {}
        self._selection_connected_layer = None
        self._series_geoms = []

        self._last_hover_x = None
        self._hover_marker = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
        self._hover_marker.setColor(QColor(255, 255, 0))
        self._hover_marker.setIcon(QgsRubberBand.ICON_CIRCLE)
        self._hover_marker.setIconSize(14)
        self._hover_marker.setWidth(2)
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
        self.chart.click_callback = self._on_chart_click

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
        self.y_field_combo.addItems(sorted(PROFILE_TYPES))
        self.y_field_combo.currentIndexChanged.connect(self._update_chart)
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
        self.sample_status_label = QLabel('No samples yet.')
        source_layout.addWidget(self.sample_status_label)
        right.addWidget(source_box)
        self.line_layer_combo.layerChanged.connect(self._on_line_layer_combo_changed)

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
        self.dem_table.itemChanged.connect(self._on_dem_table_changed)
        dem_layout.addWidget(self.dem_table)

        self.remove_dem_btn = QPushButton('Remove Layer')
        self.remove_dem_btn.clicked.connect(self._on_remove_dem_layer)
        dem_layout.addWidget(self.remove_dem_btn)
        right.addWidget(dem_box)

        options_box = QGroupBox('Options')
        options_form = QFormLayout(options_box)
        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItems(
            ['Temporary polyline', 'Selected polyline', 'Selected layer']
        )
        self.selection_mode_combo.activated.connect(self._on_selection_mode_activated)
        options_form.addRow('Selection', self.selection_mode_combo)
        self.show_cursor_check = QCheckBox('Show cursor')
        self.show_cursor_check.setChecked(True)
        self.show_cursor_check.toggled.connect(self._on_show_cursor_toggled)
        options_form.addRow('', self.show_cursor_check)
        self.link_canvas_check = QCheckBox('Link mouse position on graph with canvas')
        self.link_canvas_check.setChecked(True)
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.table_scroll_content = QWidget()
        self.table_scroll_layout = QVBoxLayout(self.table_scroll_content)
        scroll.setWidget(self.table_scroll_content)
        layout.addWidget(scroll)

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
        self.live_update_check.setChecked(True)
        sampling_form.addRow('', self.live_update_check)
        self.add_point_check = QCheckBox("Save selected points in layer 'profile_points'")
        sampling_form.addRow('', self.add_point_check)
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

    def _on_line_drawn(self, geom):
        self.line_geom = geom
        self.line_crs = QgsProject.instance().crs()
        length = geom.length()
        self.line_status_label.setText(f'Drawn line: {length:.1f} m, {geom.constGet().nCoordinates()} vertices.')
        self._restore_map_tool()
        self._resample()
        self._activate_draw_tool()

    def _restore_map_tool(self):
        self.canvas.setMapTool(self._previous_map_tool)

    def _deactivate_custom_tools(self):
        if self.canvas.mapTool() is self.draw_tool:
            self.canvas.unsetMapTool(self.canvas.mapTool())

    def _on_selection_mode_activated(self, index):
        text = self.selection_mode_combo.itemText(index)
        self._deactivate_custom_tools()
        if text == 'Temporary polyline':
            self._activate_draw_tool()
        self._resample()

    def _on_line_layer_combo_changed(self, _layer):
        if self.selection_mode_combo.currentText() in ('Selected polyline', 'Selected layer'):
            self._resample()

    def _resolve_line_geometries(self):
        """Returns a list of (geom, crs, label) tuples to profile. Both
        'Selected polyline' and 'Selected layer' work off the normal QGIS
        layer-panel selection on the chosen line layer (the original
        profiletool approach): 'Selected polyline' profiles the feature(s)
        currently selected, 'Selected layer' profiles every feature in the
        layer regardless of selection. 'Temporary polyline' uses the last
        line drawn on the canvas."""
        mode = self.selection_mode_combo.currentText()
        if mode == 'Selected layer':
            layer = self.line_layer_combo.currentLayer()
            if layer is None:
                return []
            return [
                (feature.geometry(), layer.crs(), f'#{feature.id()}')
                for feature in layer.getFeatures()
                if not feature.geometry().isEmpty()
            ]
        if mode == 'Selected polyline':
            layer = self.line_layer_combo.currentLayer()
            if layer is None:
                return []
            selected = layer.selectedFeatures()
            if not selected:
                return []
            if len(selected) == 1:
                return [(selected[0].geometry(), layer.crs(), None)]
            return [
                (feature.geometry(), layer.crs(), f'#{feature.id()}')
                for feature in selected
                if not feature.geometry().isEmpty()
            ]
        # 'Temporary polyline' uses the last drawn line geometry.
        if self.line_geom is None:
            return []
        return [(self.line_geom, self.line_crs, None)]

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
            band_spin.valueChanged.connect(self._on_dem_table_changed)
            self.dem_table.setCellWidget(row, 3, band_spin)
            buffer_spin = QDoubleSpinBox()
            buffer_spin.setEnabled(False)
            self.dem_table.setCellWidget(row, 4, buffer_spin)
        else:
            field_combo = QComboBox()
            field_combo.addItems(numeric_fields)
            field_combo.currentIndexChanged.connect(self._on_dem_table_changed)
            self.dem_table.setCellWidget(row, 3, field_combo)
            buffer_spin = QDoubleSpinBox()
            buffer_spin.setRange(0.01, 100_000)
            buffer_spin.setDecimals(2)
            buffer_spin.setValue(5)
            buffer_spin.setSuffix(' m')
            buffer_spin.valueChanged.connect(self._on_dem_table_changed)
            self.dem_table.setCellWidget(row, 4, buffer_spin)

        self._resample()

    def _on_remove_dem_layer(self):
        rows = sorted({idx.row() for idx in self.dem_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.dem_table.removeRow(row)
        self._resample()

    def _on_dem_table_changed(self, *_args):
        self._resample()

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
            buffer_widget = self.dem_table.cellWidget(row, 4)
            if field_widget is None or buffer_widget is None:
                continue
            param = field_widget.value() if kind == 'raster' else field_widget.currentText()
            buffer = buffer_widget.value()
            yield layer, kind, param, color, buffer

    # ---- DEM sampling ---------------------------------------------------

    def _collect_series(self, geom, crs, interval, label=None):
        series = []
        for layer, kind, param, color, buffer in self._checked_dem_rows():
            if kind == 'raster':
                if param > layer.bandCount():
                    continue
                samples = sample_profile(geom, layer, interval, crs, band=param)
                base_name = f'{layer.name()}_band_{param}'
            else:
                samples = sample_profile_vector(geom, layer, param, buffer, crs)
                base_name = f'{layer.name()}_{param}'
            name = base_name if label is None else f'{base_name} ({label})'
            series.append((name, samples, color if label is None else None))
        return series

    def _sync_layer_connections(self):
        """Connect dataChanged on checked DEM layers (and, in 'Selected
        layer' mode, the active line layer) so the profile auto-refreshes
        when the underlying data is edited."""
        mode = self.selection_mode_combo.currentText()
        wanted = {layer.id(): layer for layer, _kind, _p, _c, _b in self._checked_dem_rows()}
        if mode == 'Selected layer':
            line_layer = self.line_layer_combo.currentLayer()
            if line_layer is not None:
                wanted[line_layer.id()] = line_layer

        for layer_id in list(self._connected_layers):
            if layer_id not in wanted:
                layer = self._connected_layers.pop(layer_id)
                try:
                    layer.dataChanged.disconnect(self._resample)
                except (TypeError, RuntimeError):
                    pass

        for layer_id, layer in wanted.items():
            if layer_id not in self._connected_layers:
                layer.dataChanged.connect(self._resample)
                self._connected_layers[layer_id] = layer

        # Auto-refresh on layer-panel selection changes for 'Selected polyline'.
        desired_selection_layer = self.line_layer_combo.currentLayer() if mode == 'Selected polyline' else None
        if self._selection_connected_layer is not desired_selection_layer:
            if self._selection_connected_layer is not None:
                try:
                    self._selection_connected_layer.selectionChanged.disconnect(self._resample)
                except (TypeError, RuntimeError):
                    pass
            self._selection_connected_layer = desired_selection_layer
            if desired_selection_layer is not None:
                desired_selection_layer.selectionChanged.connect(self._resample)

    def _resample(self):
        """Re-sample and re-plot from the current line and checked DEM
        layers. Called automatically whenever the line, layer selection, or
        DEM table change (no explicit "Sample Elevation" button, matching
        profiletool's always-live behaviour)."""
        self._sync_layer_connections()

        geoms = [(g, c, l) for g, c, l in self._resolve_line_geometries() if g is not None and g.length() > 0]
        if not geoms:
            self.sample_status_label.setText('No samples yet.')
            self.export_to_map_btn.setEnabled(False)
            return

        checked = list(self._checked_dem_rows())
        if not checked:
            self.sample_status_label.setText('No DEM layers checked.')
            self.export_to_map_btn.setEnabled(False)
            return

        interval = self.sample_interval.value()
        longest = max(g.length() for g, _c, _l in geoms)
        if int(longest / interval) + 1 > MAX_SAMPLE_COUNT:
            self.sample_status_label.setText('Line too long for this sample interval; increase the interval.')
            return

        primary_geom, primary_crs, _label = geoms[0]
        self.line_geom = primary_geom
        self.line_crs = primary_crs
        self.line_manager.update(primary_geom, primary_crs.authid())

        self._series = []
        self._series_geoms = []
        for geom, crs, label in geoms:
            new_series = self._collect_series(geom, crs, interval, label=label)
            self._series.extend(new_series)
            self._series_geoms.extend([(geom, crs)] * len(new_series))
        if not self._series:
            self.sample_status_label.setText('No DEM layers could be sampled (check band/field settings).')
            self.export_to_map_btn.setEnabled(False)
            return

        self.samples = self._series[0][1]

        valid = [s for s in self.samples if s[2]]
        n_gaps = sum(1 for s in self.samples if not s[2])
        if not valid:
            self.sample_status_label.setText('No valid elevation samples were found along this line.')
            self.export_to_map_btn.setEnabled(False)
            return

        elevations = [e for _, e, _ in valid]
        self.y_min.setValue(min(elevations) - 5)
        self.y_max.setValue(max(elevations) + 5)

        feature_note = f', {len(geoms)} feature(s)' if len(geoms) > 1 else ''
        self.sample_status_label.setText(
            f'{len(checked)} DEM(s) sampled{feature_note}, {len(self.samples)} samples on first layer, {n_gaps} gap(s).'
        )
        self.export_to_map_btn.setEnabled(True)

        self._sync_chart_range_from_settings()
        self._update_chart()
        self._populate_samples_table()

    # ---- Profile chart ---------------------------------------------------

    def _sync_chart_range_from_settings(self):
        self.chart_y_min.setValue(self.y_min.value())
        self.chart_y_max.setValue(self.y_max.value())

    def _display_series(self):
        profiler, y_label = PROFILE_TYPES[self.y_field_combo.currentText()]
        return [(name, profiler(samples), color) for name, samples, color in self._series], y_label

    def _update_chart(self):
        if not self._series:
            return
        display_series, y_label = self._display_series()
        self.chart.set_data(display_series, interpolated=self.interp_check.isChecked(), y_label=y_label)
        if self.y_field_combo.currentText() == 'Height':
            self.chart.set_y_range(self.chart_y_min.value(), self.chart_y_max.value())
        else:
            self.chart.reset_view()

    def _live_resample(self, geom, crs):
        if geom.length() <= 0:
            return
        interval = self.sample_interval.value()
        if int(geom.length() / interval) + 1 > MAX_SAMPLE_COUNT:
            return

        series = self._collect_series(geom, crs, interval)
        if not series:
            return
        self._series = series
        self.samples = series[0][1]
        self._update_chart()

    def _on_chart_range_changed(self, _value):
        self.chart.set_y_range(self.chart_y_min.value(), self.chart_y_max.value())

    def _on_show_cursor_toggled(self, checked):
        self.chart.show_cursor = checked
        if not checked:
            self.chart.hide_crosshair()

    def _on_chart_mouse_move(self, x, y):
        self._last_hover_x = x
        if x is None or y is None or not self.show_cursor_check.isChecked():
            self.x_readout.setText('/')
            self.y_readout.setText('/')
        else:
            self.x_readout.setText(f'{x:.2f}')
            self.y_readout.setText(f'{y:.2f}')
        self._update_hover_marker(x)

    def _on_chart_click(self, x, _y):
        if x is None or not self.add_point_check.isChecked() or not self.samples or self.line_geom is None:
            return
        valid = [s for s in self.samples if s[2]]
        if not valid:
            return
        distance, elevation, _ok = min(valid, key=lambda s: abs(s[0] - x))
        self._add_profile_point(distance, elevation)

    def _add_profile_point(self, distance, elevation):
        layer = self._get_profile_points_layer()
        point = self.line_geom.interpolate(distance).asPoint()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(point))
        feature.setAttributes([distance, elevation])
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        layer.triggerRepaint()
        self.iface.messageBar().pushSuccess('Profile Plot', f'Point added at distance {distance:.2f} m.')

    def _get_profile_points_layer(self):
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if layer.name() == 'profile_points':
                return layer
        crs_authid = self.line_crs.authid() if self.line_crs else project.crs().authid()
        layer = QgsVectorLayer(f'Point?crs={crs_authid}', 'profile_points', 'memory')
        provider = layer.dataProvider()
        provider.addAttributes([QgsField('d', QVariant.Double), QgsField('z', QVariant.Double)])
        layer.updateFields()
        project.addMapLayer(layer)
        return layer

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
        layout = self.table_scroll_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for (name, samples, _color), (geom, crs) in zip(self._series, self._series_geoms):
            group = QGroupBox(name)
            group_layout = QVBoxLayout(group)

            table = QTableWidget(2, len(samples))
            table.setVerticalHeaderLabels(['1', '2'])
            for col, (distance, elevation, is_valid) in enumerate(samples):
                table.setItem(0, col, QTableWidgetItem(f'{distance:.3f}'))
                table.setItem(1, col, QTableWidgetItem(f'{elevation:.3f}' if is_valid else ''))
            table.resizeColumnsToContents()
            table.setMaximumHeight(table.verticalHeader().length() + table.horizontalHeader().height() + 6)
            group_layout.addWidget(table)

            button_row = QHBoxLayout()
            copy_btn = QPushButton('Copy to clipboard')
            copy_btn.clicked.connect(lambda _checked=False, s=samples: self._copy_series(s))
            button_row.addWidget(copy_btn)
            copy_coords_btn = QPushButton('Copy to clipboard (with coordinates)')
            copy_coords_btn.clicked.connect(lambda _checked=False, s=samples, g=geom: self._copy_series_with_coords(s, g))
            button_row.addWidget(copy_coords_btn)
            create_layer_btn = QPushButton('Create Temporary layer')
            create_layer_btn.clicked.connect(
                lambda _checked=False, s=samples, g=geom, c=crs, n=name: self._create_temp_layer_for(s, g, c, n)
            )
            button_row.addWidget(create_layer_btn)
            group_layout.addLayout(button_row)

            layout.addWidget(group)

        layout.addStretch(1)

    def _copy_series(self, samples):
        text = '\n'.join(f'{d}\t{e}' for d, e, ok in samples if ok)
        QApplication.clipboard().setText(text)

    def _copy_series_with_coords(self, samples, geom):
        if geom is None:
            return
        lines = []
        for d, e, ok in samples:
            if not ok:
                continue
            point = geom.interpolate(d).asPoint()
            lines.append(f'{d}\t{point.x()}\t{point.y()}\t{e}')
        QApplication.clipboard().setText('\n'.join(lines))

    def _create_temp_layer_for(self, samples, geom, crs, name):
        if geom is None:
            return
        crs_authid = crs.authid() if crs else QgsProject.instance().crs().authid()
        layer = QgsVectorLayer(f'Point?crs={crs_authid}', f'ProfileTool_{name}', 'memory')
        provider = layer.dataProvider()
        provider.addAttributes([QgsField('Value', QVariant.Double)])
        layer.updateFields()

        features = []
        for d, e, ok in samples:
            if not ok:
                continue
            point = geom.interpolate(d).asPoint()
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

    def showEvent(self, event):
        super().showEvent(event)
        self._on_selection_mode_activated(self.selection_mode_combo.currentIndex())

    def closeEvent(self, event):
        if self.canvas.mapTool() in (self.draw_tool, self.pick_tool):
            self.canvas.unsetMapTool(self.canvas.mapTool())
        self._hover_marker.reset(QgsWkbTypes.PointGeometry)
        self.line_manager.reset()
        for layer in list(self._connected_layers.values()):
            try:
                layer.dataChanged.disconnect(self._resample)
            except (TypeError, RuntimeError):
                pass
        self._connected_layers.clear()
        if self._selection_connected_layer is not None:
            try:
                self._selection_connected_layer.selectionChanged.disconnect(self._resample)
            except (TypeError, RuntimeError):
                pass
            self._selection_connected_layer = None
        super().closeEvent(event)
