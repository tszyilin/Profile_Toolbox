# -*- coding: utf-8 -*-
"""Equal Area Slope tab, embedded in the Profile Tool dock widget.

Provides two workflows:

* Batch mode (top): pick a line shapefile + DEM and process every feature,
  saving PNGs and a log to an output folder. Mirrors the standalone tkinter
  tool from `equal_area_slope_v4.py`.
* Single-profile results view (bottom): shows the EAS plot + numeric summary
  for the profile currently drawn in the Profile tab. Populated by
  `show_profile_result()` when the user clicks the "Calculate Equal Area
  Slope" button in the Profile tab.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..tools.equal_area_slope import run_equal_area_slope, compute_equal_area_slope


class EqualAreaSlopeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- Batch inputs ------------------------------------------------
        self.shapefile_edit = QLineEdit()
        self.raster_edit = QLineEdit()
        self.id_combo = QComboBox()
        self.id_combo.setEditable(True)
        self.out_fol_edit = QLineEdit()
        self.out_file_edit = QLineEdit('EAS_output')
        self.interval_edit = QLineEdit('10')

        for w in (self.shapefile_edit, self.raster_edit, self.out_fol_edit,
                  self.out_file_edit):
            w.setMinimumWidth(280)

        browse_shp = QPushButton('Browse...')
        browse_shp.clicked.connect(self.browse_shapefile)
        browse_ras = QPushButton('Browse...')
        browse_ras.clicked.connect(self.browse_raster)
        load_fields = QPushButton('Load fields')
        load_fields.clicked.connect(self.load_fields)
        browse_out = QPushButton('Browse...')
        browse_out.clicked.connect(self.browse_out_fol)

        batch_grid = QGridLayout()
        r = 0
        batch_grid.addWidget(QLabel('Input shapefile (.shp):'), r, 0)
        batch_grid.addWidget(self.shapefile_edit, r, 1)
        batch_grid.addWidget(browse_shp, r, 2)
        r += 1
        batch_grid.addWidget(QLabel('Input raster (DEM):'), r, 0)
        batch_grid.addWidget(self.raster_edit, r, 1)
        batch_grid.addWidget(browse_ras, r, 2)
        r += 1
        batch_grid.addWidget(QLabel('Unique identifier field:'), r, 0)
        batch_grid.addWidget(self.id_combo, r, 1)
        batch_grid.addWidget(load_fields, r, 2)
        r += 1
        batch_grid.addWidget(QLabel('Output folder:'), r, 0)
        batch_grid.addWidget(self.out_fol_edit, r, 1)
        batch_grid.addWidget(browse_out, r, 2)
        r += 1
        batch_grid.addWidget(QLabel('Output file prefix:'), r, 0)
        batch_grid.addWidget(self.out_file_edit, r, 1)
        r += 1
        batch_grid.addWidget(QLabel('Sampling interval (m):'), r, 0)
        batch_grid.addWidget(self.interval_edit, r, 1)
        r += 1

        run_batch_btn = QPushButton('Run batch')
        run_batch_btn.clicked.connect(self.on_run_batch)
        batch_btn_row = QHBoxLayout()
        batch_btn_row.addStretch(1)
        batch_btn_row.addWidget(run_batch_btn)

        batch_box = QGroupBox('Batch (shapefile + DEM)')
        batch_layout = QVBoxLayout()
        batch_layout.addLayout(batch_grid)
        batch_layout.addLayout(batch_btn_row)
        batch_box.setLayout(batch_layout)

        # ---- Single-profile results view ---------------------------------
        self.result_label = QLabel(
            'No result yet. Draw a profile, then click '
            '"Calculate Equal Area Slope" in the Profile tab.')
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._canvas = None  # lazy; matplotlib may load slowly

        self.result_box = QGroupBox('Current profile result')
        self._result_layout = QVBoxLayout()
        self._result_layout.addWidget(self.result_label)
        self.result_box.setLayout(self._result_layout)

        outer = QVBoxLayout()
        outer.addWidget(batch_box)
        outer.addWidget(self.result_box, 1)
        self.setLayout(outer)

    # ---------------------------------------------------------------------
    # Batch flow
    # ---------------------------------------------------------------------
    def browse_shapefile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select input line shapefile', '',
            'Shapefiles (*.shp);;All files (*.*)')
        if path:
            self.shapefile_edit.setText(path)
            self.load_fields()

    def browse_raster(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select input raster (DEM)', '',
            'Raster files (*.tif *.tiff *.img *.vrt);;All files (*.*)')
        if path:
            self.raster_edit.setText(path)

    def browse_out_fol(self):
        path = QFileDialog.getExistingDirectory(self, 'Select output folder')
        if path:
            self.out_fol_edit.setText(path)

    def load_fields(self):
        shp = self.shapefile_edit.text().strip()
        if not shp or not os.path.isfile(shp):
            QMessageBox.warning(self, 'Load fields',
                                'Please select a valid shapefile first.')
            return
        try:
            import geopandas as gpd
            gdf = gpd.read_file(shp, rows=1)
            fields = [c for c in gdf.columns if c != 'geometry']
            current = self.id_combo.currentText()
            self.id_combo.clear()
            self.id_combo.addItems(fields)
            if current:
                self.id_combo.setCurrentText(current)
            elif fields:
                self.id_combo.setCurrentText(fields[0])
        except Exception as exc:
            QMessageBox.critical(self, 'Load fields',
                                 f'Could not read shapefile fields:\n{exc}')

    def on_run_batch(self):
        shp = self.shapefile_edit.text().strip()
        raster = self.raster_edit.text().strip()
        id_header = self.id_combo.currentText().strip()
        out_fol = self.out_fol_edit.text().strip()
        out_file = self.out_file_edit.text().strip()
        interval_txt = self.interval_edit.text().strip()

        if not shp or not os.path.isfile(shp):
            QMessageBox.critical(self, 'Input error', 'Please select a valid input shapefile.')
            return
        if not raster or not os.path.isfile(raster):
            QMessageBox.critical(self, 'Input error', 'Please select a valid input raster.')
            return
        if not out_fol:
            QMessageBox.critical(self, 'Input error', 'Please select an output folder.')
            return
        if not out_file:
            QMessageBox.critical(self, 'Input error', 'Please provide an output file prefix.')
            return
        try:
            interval = float(interval_txt)
            if interval <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.critical(self, 'Input error', 'Sampling interval must be a positive number.')
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            results = run_equal_area_slope(shp, raster, id_header, out_fol, out_file, interval)
            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self, 'Done',
                f'Processing complete. {len(results)} line(s) processed.\n'
                f'Plots saved to:\n{out_fol}')
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, 'Processing error', f'An error occurred:\n{exc}')

    # ---------------------------------------------------------------------
    # Single-profile results view (called from the Profile tab)
    # ---------------------------------------------------------------------
    def show_profile_result(self, distances_m, elevations, label=None):
        """Compute EAS on an in-memory profile and display it in this tab."""
        try:
            res = compute_equal_area_slope(distances_m, elevations)
        except Exception as exc:
            QMessageBox.critical(self, 'Equal Area Slope',
                                 f'Could not compute EAS:\n{exc}')
            return

        self.result_label.setText(
            f"{label + '  |  ' if label else ''}"
            f"Length: {res['length_km']:.3f} km   "
            f"Equal-area slope: {res['equal_area_slope']:.3f} m/km   "
            f"Average slope: {res['average_slope']:.3f} m/km   "
            f"Area cut: {res['area_cut']:.4f}   "
            f"Area fill: {res['area_fill']:.4f}")

        self._ensure_canvas()
        if self._canvas is None:
            return

        fig = self._canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        d = res['distances_km']
        z = res['elevations']
        eas = res['equal_area_line']
        avg = res['average_line']

        ax.plot(d, z, color='black', label='Longitudinal Profile')
        ax.plot(d, eas, color='red', linestyle='--', label='Equal Area Slope Line')
        ax.plot(d, avg, color='black', linestyle=':', label='Average Slope Line')
        ax.fill_between(d, z, eas, where=(z > eas), color='purple', alpha=0.3,
                        label='Area below (cut - upstream)')
        ax.fill_between(d, eas, z, where=(eas > z), color='green', alpha=0.3,
                        label='Area above (fill - downstream)')
        ax.set_xlabel('Distance (km)')
        ax.set_ylabel('Elevation (m)')
        ax.grid(True)
        ax.legend(loc='best', fontsize='small')
        fig.tight_layout()
        self._canvas.draw_idle()

    def _ensure_canvas(self):
        if self._canvas is not None:
            return
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except ImportError:
            try:
                from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
                from matplotlib.figure import Figure
            except ImportError as exc:
                QMessageBox.critical(self, 'Equal Area Slope',
                                     f'matplotlib is required for the plot:\n{exc}')
                return
        fig = Figure(figsize=(6, 3.5))
        self._canvas = FigureCanvasQTAgg(fig)
        self._result_layout.addWidget(self._canvas, 1)
