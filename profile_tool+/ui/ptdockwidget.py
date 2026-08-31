# -*- coding: utf-8 -*-
# -----------------------------------------------------------
#
# Profile
# Copyright (C) 2012  Patrice Verchere
# -----------------------------------------------------------
#
# licensed under the terms of GNU GPL 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, print to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# ---------------------------------------------------------------------

import os
from contextlib import suppress

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMapLayer,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

# from qgis.gui import *
# from qgis.PyQt import QtCore, QtGui, uic
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QModelIndex, Qt, QVariant, pyqtSignal
from qgis.PyQt.QtGui import QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDockWidget,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# plugin import
from ..tools.plottingtool import PlottingTool
from .. import pyqtgraph as pg
from ..tools.profile_stats import compute_stats, segment_stats
from .toggle_switch import ToggleSwitch
from ..tools.tableviewtool import TableViewTool

try:
    import matplotlib  # noqa:F401
    from matplotlib import *  # noqa:F403,F401

    matplotlib_loaded = True
except ImportError:
    matplotlib_loaded = False


uiFilePath = os.path.abspath(os.path.join(os.path.dirname(__file__), "profiletool.ui"))
FormClass = uic.loadUiType(uiFilePath)[0]


class PTDockWidget(QDockWidget, FormClass):

    TITLE = "ProfileTool"
    TYPE = None

    closed = pyqtSignal()

    def __init__(self, iface1, profiletoolcore, parent=None):
        QDockWidget.__init__(self, parent)
        self.setupUi(self)

        # Segment measurement state (chainages picked on the plot).
        self._segment_start = None
        self._segment_end = None
        self._segment_items = []

        # Statistics panel, between the plot and the layer list.
        try:
            self._buildStatsPanel()
        except Exception as e:  # noqa: BLE001
            self.statsTable = None
            QgsMessageLog.logMessage(
                "Statistics panel could not be built: {}".format(e),
                "ProfileTool",
                Qgis.MessageLevel.Warning,
            )

        self.profiletoolcore = profiletoolcore
        self.iface = iface1
        # Apperance
        self.location = Qt.DockWidgetArea.BottomDockWidgetArea
        minsize = self.minimumSize()
        maxsize = self.maximumSize()
        self.setMinimumSize(minsize)
        self.setMaximumSize(maxsize)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # init scale widgets
        self.sbMaxVal.setValue(0)
        self.sbMinVal.setValue(0)
        self.sbMaxVal.setEnabled(False)
        self.sbMinVal.setEnabled(False)
        self.connectYSpinbox()

        # model
        self.mdl = QStandardItemModel(
            0, 6
        )  # the model whitch in are saved layers analysed caracteristics
        self.tableView.setModel(self.mdl)
        self.tableView.setColumnWidth(0, 20)
        self.tableView.setColumnWidth(1, 20)
        # self.tableView.setColumnWidth(2, 150)
        hh = self.tableView.horizontalHeader()
        hh.setStretchLastSection(True)
        self.tableView.setColumnHidden(5, True)
        self.mdl.setHorizontalHeaderLabels(
            ["", "", self.tr("Layer"), self.tr("Band/Field"), self.tr("Search buffer")]
        )
        self.tableViewTool = TableViewTool()

        # other
        self.addOptionComboboxItems()
        self.selectionmethod = 0
        self.plotlibrary = None  # The plotting library to use
        self.showcursor = True

        # Signals
        self.butSaveAs.clicked.connect(self.saveAs)
        self.tableView.clicked.connect(self._onClick)
        self.mdl.itemChanged.connect(self._onChange)
        self.pushButton_2.clicked.connect(self.addLayer)
        self.pushButton.clicked.connect(self.removeLayer)
        self.comboBox.currentIndexChanged.connect(self.selectionMethod)
        self.cboLibrary.currentIndexChanged.connect(self.changePlotLibrary)
        self.tableViewTool.layerAddedOrRemoved.connect(self.refreshPlot)
        self.pushButton_reinitview.clicked.connect(self.reScalePlot)
        self.checkBox_showcursor.stateChanged.connect(self.showCursor)
        self.cbLiveUpdate.stateChanged.connect(self.liveUpdateChanged)
        self.fullResolutionCheckBox.stateChanged.connect(self.refreshPlot)
        self.profileInterpolationCheckBox.stateChanged.connect(self.refreshPlot)

        self.cbSameAxisScale.stateChanged.connect(self._onSameAxisScaleStateChanged)

        # "Save drawn line as layer" button, in the Options group.
        self._buildSaveDrawnLineButton()

    # ********************************************************************************
    # init things ****************************************************************
    # ********************************************************************************

    def addOptionComboboxItems(self):
        self.cboLibrary.addItem("PyQtGraph")
        if matplotlib_loaded:
            self.cboLibrary.addItem("Matplotlib")

    def selectionMethod(self, item):
        self.profiletoolcore.toolrenderer.setSelectionMethod(item)

        if self.iface.mapCanvas().mapTool() == self.profiletoolcore.toolrenderer.tool:
            self.iface.mapCanvas().setMapTool(self.profiletoolcore.toolrenderer.tool)
            self.profiletoolcore.toolrenderer.connectTool()

    def changePlotLibrary(self, item):
        self.plotlibrary = self.cboLibrary.itemText(item)
        self.addPlotWidget(self.plotlibrary)

        if self.plotlibrary == "PyQtGraph":
            self.checkBox_mpl_tracking.setEnabled(True)
            self.checkBox_showcursor.setEnabled(True)
            self.checkBox_mpl_tracking.setCheckState(Qt.CheckState.Checked)
            self.profiletoolcore.activateMouseTracking(2)
            self.checkBox_mpl_tracking.stateChanged.connect(
                self.profiletoolcore.activateMouseTracking
            )
            self._onSameAxisScaleStateChanged(self.cbSameAxisScale.checkState())

        elif self.plotlibrary == "Matplotlib":
            self.checkBox_mpl_tracking.setEnabled(True)
            self.checkBox_showcursor.setEnabled(False)
            self.checkBox_mpl_tracking.setCheckState(Qt.CheckState.Checked)
            self.profiletoolcore.activateMouseTracking(2)
            self.checkBox_mpl_tracking.stateChanged.connect(
                self.profiletoolcore.activateMouseTracking
            )
            self.cbSameAxisScale.setCheckState(Qt.CheckState.Unchecked)

        else:
            self.checkBox_mpl_tracking.setCheckState(Qt.CheckState.Unchecked)
            self.checkBox_mpl_tracking.setEnabled(False)
            self.cbSameAxisScale.setCheckState(Qt.CheckState.Unchecked)

        self.cbSameAxisScale.setEnabled(self.plotlibrary == "PyQtGraph")

    def addPlotWidget(self, library):
        layout = self.frame_for_plot.layout()

        while layout.count():
            child = layout.takeAt(0)
            child.widget().deleteLater()

        if library == "PyQtGraph":
            self.stackedWidget.setCurrentIndex(0)
            self.plotWdg = PlottingTool().changePlotWidget("PyQtGraph", self.frame_for_plot)
            layout.addWidget(self.plotWdg)
            self.TYPE = "PyQtGraph"
            self.cbxSaveAs.clear()
            self.cbxSaveAs.addItems(
                ["Graph - PNG", "Graph - SVG", "3D line - DXF", "2D Profile - DXF"]
            )

        elif library == "Matplotlib":
            self.stackedWidget.setCurrentIndex(0)
            # self.widget_save_buttons.setVisible( False )
            self.plotWdg = PlottingTool().changePlotWidget("Matplotlib", self.frame_for_plot)
            layout.addWidget(self.plotWdg)
            self.TYPE = "Matplotlib"
            self.cbxSaveAs.clear()
            self.cbxSaveAs.addItems(
                [
                    "Graph - PDF",
                    "Graph - PNG",
                    "Graph - SVG",
                    "Graph - print (PS)",
                    "3D line - DXF",
                    "2D Profile - DXF",
                ]
            )

    # ********************************************************************************
    # graph things ****************************************************************
    # ********************************************************************************

    def connectYSpinbox(self):
        self.sbMinVal.valueChanged.connect(self.reScalePlot)
        self.sbMaxVal.valueChanged.connect(self.reScalePlot)

    def disconnectYSpinbox(self):
        with suppress(AttributeError, RuntimeError, TypeError):
            self.sbMinVal.valueChanged.disconnect(self.reScalePlot)
            self.sbMaxVal.valueChanged.disconnect(self.reScalePlot)

    def connectPlotRangechanged(self):
        self.plotWdg.getViewBox().sigRangeChanged.connect(self.plotRangechanged)

    def disconnectPlotRangechanged(self):
        with suppress(AttributeError, RuntimeError, TypeError):
            self.plotWdg.getViewBox().sigRangeChanged.disconnect(self.plotRangechanged)

    def plotRangechanged(self, param=None):  # called when pyqtgraph view changed
        PlottingTool().plotRangechanged(self, self.cboLibrary.currentText())

    def liveUpdateChanged(self, state):
        self.profiletoolcore.liveUpdate = state

    def reScalePlot(self, param):  # called when a spinbox value changed
        if isinstance(param, bool):  # comes from button
            PlottingTool().reScalePlot(
                self, self.profiletoolcore.profiles, self.cboLibrary.currentText(), True
            )

        else:  # spinboxchanged
            if self.sbMinVal.value() == self.sbMaxVal.value() == 0:
                # don't execute it on init
                pass
            else:
                PlottingTool().reScalePlot(
                    self, self.profiletoolcore.profiles, self.cboLibrary.currentText()
                )

    @staticmethod
    def crossLabelAxis(item):
        """Returns "X"/"Y" if the TextItem is one of the crosshair readout
        labels, otherwise None."""
        try:
            text = item.textItem.toPlainText()
        except (AttributeError, RuntimeError):
            return None
        return text[0] if text[:1] in ("X", "Y") else None

    def showCursor(self, int1):
        # For pyqtgraph mode
        if self.plotlibrary == "PyQtGraph":
            if int1 == 2:
                self.showcursor = True
                self.profiletoolcore.doTracking = bool(self.checkBox_mpl_tracking.checkState())
                self.checkBox_mpl_tracking.setEnabled(True)
                for item in self.plotWdg.allChildItems():
                    if isinstance(item, pg.InfiniteLine):
                        if item.name() in ("cross_vertical", "cross_horizontal"):
                            item.show()
                    elif isinstance(item, pg.TextItem):
                        if self.crossLabelAxis(item) in ("X", "Y"):
                            item.show()
            elif int1 == 0:
                self.showcursor = False
                self.profiletoolcore.doTracking = False
                self.checkBox_mpl_tracking.setEnabled(False)

                for item in self.plotWdg.allChildItems():
                    if isinstance(item, pg.InfiniteLine):
                        if item.name() in ("cross_vertical", "cross_horizontal"):
                            item.hide()
                    elif isinstance(item, pg.TextItem):
                        if self.crossLabelAxis(item) in ("X", "Y"):
                            item.hide()
            self.profiletoolcore.plotProfil()

    # ********************************************************************************
    # tablebiew things ****************************************************************
    # ********************************************************************************

    def addLayer(self, layer1=None):
        if isinstance(layer1, bool):  # comes from click
            layer1 = self.iface.activeLayer()

        self.tableViewTool.addLayer(self.iface, self.mdl, layer1)
        self.profiletoolcore.updateProfil(self.profiletoolcore.pointstoDraw, False)
        if layer1 is None: # no layer selected in the dropdown
            return
        layer1.dataChanged.connect(self.refreshPlot)

    def removeLayer(self, index=None):
        if isinstance(index, bool):  # come from button
            index = self.tableViewTool.chooseLayerForRemoval(self.iface, self.mdl)

        if index is not None:
            layer = self.mdl.index(index, 4).data()
            with suppress(AttributeError, RuntimeError, TypeError):
                layer.dataChanged.disconnect(self.refreshPlot)
            self.tableViewTool.removeLayer(self.mdl, index)
        self.profiletoolcore.updateProfil(self.profiletoolcore.pointstoDraw, False, True)

    def refreshPlot(self):
        #
        #    Refreshes/updates the plot without requiring the user to
        #    redraw the plot line (rubberband)
        #
        self.profiletoolcore.updateProfil(self.profiletoolcore.pointstoDraw, False, True)

    def _onClick(self, index1):  # action when clicking the tableview
        self.tableViewTool.onClick(self.iface, self, self.mdl, self.plotlibrary, index1)

    def _onChange(self, item):
        if (
            not self.mdl.item(item.row(), 5) is None
            and item.column() == 4
            and self.mdl.item(item.row(), 5).data(Qt.ItemDataRole.EditRole).type()
            == QgsMapLayer.LayerType.VectorLayer
        ):

            self.profiletoolcore.plotProfil()

    def _onSameAxisScaleStateChanged(self, state):
        """
        Called whenever the checkbox button for same scale axis status has changed
        if checked, plot will always keep same scale on both axis (aspect ratio of 1)

        Only supported with PyQtGraph
        """

        if self.plotlibrary == "PyQtGraph":
            self.plotWdg.getViewBox().setAspectLocked(state == Qt.CheckState.Checked)

    # ********************************************************************************
    # coordinate tab ****************************************************************
    # ********************************************************************************
    @staticmethod
    def _profile_name(profile):
        groupTitle = profile["layer"].name()
        band = profile["band"]
        if band is not None and band > -1:
            groupTitle += "_band_{}".format(band)
        return groupTitle.replace(" ", "_")

    def updateCoordinateTab(self):

        try:  # Reinitializing the table tab
            self.VLayout = self.scrollAreaWidgetContents.layout()
            while 1:
                child = self.VLayout.takeAt(0)
                if not child:
                    break
                child.widget().deleteLater()
        except Exception:
            self.VLayout = QVBoxLayout(self.scrollAreaWidgetContents)
            self.VLayout.setContentsMargins(9, -1, -1, -1)
        # Setup the table tab
        self.groupBox = []
        self.profilePushButton = []
        self.coordsPushButton = []
        self.tolayerPushButton = []
        self.tableView = []
        self.verticalLayout = []
        if self.mdl.rowCount() != self.profiletoolcore.profiles:
            # keep the number of profiles and the model in sync.
            self.profiletoolcore.updateProfil(self.profiletoolcore.pointstoDraw, False, False)
        for i in range(0, self.mdl.rowCount()):
            self.groupBox.append(QGroupBox(self.scrollAreaWidgetContents))
            sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.groupBox[i].setSizePolicy(sizePolicy)
            profileTitle = self._profile_name(self.profiletoolcore.profiles[i])

            self.groupBox[i].setTitle(
                QApplication.translate("GroupBox" + str(i), profileTitle, None)
            )
            self.groupBox[i].setObjectName("groupBox" + str(i))

            self.verticalLayout.append(QVBoxLayout(self.groupBox[i]))
            self.verticalLayout[i].setObjectName("verticalLayout")
            # The table
            self.tableView.append(QTableView(self.groupBox[i]))
            sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.tableView[i].setSizePolicy(sizePolicy)
            self.tableView[i].setObjectName("tableView" + str(i))
            # font = QFont("Arial", 8)
            column = len(self.profiletoolcore.profiles[i]["l"])
            self.mdl2 = QStandardItemModel(2, column)
            for j in range(len(self.profiletoolcore.profiles[i]["l"])):
                self.mdl2.setData(
                    self.mdl2.index(0, j, QModelIndex()), self.profiletoolcore.profiles[i]["l"][j]
                )
                self.mdl2.setData(
                    self.mdl2.index(1, j, QModelIndex()), self.profiletoolcore.profiles[i]["z"][j]
                )
            self.tableView[i].verticalHeader().setDefaultSectionSize(18)
            self.tableView[i].horizontalHeader().setDefaultSectionSize(60)
            self.tableView[i].setModel(self.mdl2)
            # 2 * header (1 header + 1 horz slider) + nrows + a small margin
            minTableHeight = (
                2 * self.tableView[i].horizontalHeader().height()
                + sum(
                    self.tableView[i].rowHeight(j)
                    for j in range(self.tableView[i].model().rowCount())
                )
                + 6
            )  # extra safety margin
            self.tableView[i].setMinimumHeight(minTableHeight)

            self.verticalLayout[i].addWidget(self.tableView[i])

            self.horizontalLayout = QHBoxLayout()

            # the copy to clipboard button
            self.profilePushButton.append(QPushButton(self.groupBox[i]))
            sizePolicy = QSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
            )
            self.profilePushButton[i].setSizePolicy(sizePolicy)
            self.profilePushButton[i].setText(
                QApplication.translate("GroupBox", "Copy to clipboard", None)
            )
            self.profilePushButton[i].setObjectName(str(i))
            self.horizontalLayout.addWidget(self.profilePushButton[i])

            # button to copy to clipboard with coordinates
            self.coordsPushButton.append(QPushButton(self.groupBox[i]))
            sizePolicy = QSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
            )
            self.coordsPushButton[i].setSizePolicy(sizePolicy)
            self.coordsPushButton[i].setText(
                QApplication.translate("GroupBox", "Copy to clipboard (with coordinates)", None)
            )

            # button to copy to clipboard with coordinates
            self.tolayerPushButton.append(QPushButton(self.groupBox[i]))
            sizePolicy = QSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
            )
            self.tolayerPushButton[i].setSizePolicy(sizePolicy)
            self.tolayerPushButton[i].setText(
                QApplication.translate("GroupBox", "Create Temporary layer", None)
            )

            self.coordsPushButton[i].setObjectName(str(i))
            self.horizontalLayout.addWidget(self.coordsPushButton[i])

            self.tolayerPushButton[i].setObjectName(str(i))
            self.horizontalLayout.addWidget(self.tolayerPushButton[i])

            self.horizontalLayout.addStretch(0)
            self.verticalLayout[i].addLayout(self.horizontalLayout)

            self.VLayout.addWidget(self.groupBox[i])

            self.profilePushButton[i].clicked.connect(self.copyTable)
            self.coordsPushButton[i].clicked.connect(self.copyTableAndCoords)
            self.tolayerPushButton[i].clicked.connect(self.createTemporaryLayer)

    def copyTable(self):  # Writing the table to clipboard in excel form
        nr = int(self.sender().objectName())
        self.clipboard = QApplication.clipboard()
        text = ""
        for i in range(len(self.profiletoolcore.profiles[nr]["l"])):
            text += (
                str(self.profiletoolcore.profiles[nr]["l"][i])
                + "\t"
                + str(self.profiletoolcore.profiles[nr]["z"][i])
                + "\n"
            )
        self.clipboard.setText(text)

    def copyTableAndCoords(self):  # Writing the table with coordinates to clipboard in excel form
        nr = int(self.sender().objectName())
        self.clipboard = QApplication.clipboard()
        text = ""
        for i in range(len(self.profiletoolcore.profiles[nr]["l"])):
            text += (
                str(self.profiletoolcore.profiles[nr]["l"][i])
                + "\t"
                + str(self.profiletoolcore.profiles[nr]["x"][i])
                + "\t"
                + str(self.profiletoolcore.profiles[nr]["y"][i])
                + "\t"
                + str(self.profiletoolcore.profiles[nr]["z"][i])
                + "\n"
            )
        self.clipboard.setText(text)

    def createTemporaryLayer(self):
        nr = int(self.sender().objectName())
        type = "Point?crs=" + str(self.profiletoolcore.profiles[nr]["layer"].crs().authid())
        name = "ProfileTool_{}".format(self._profile_name(self.profiletoolcore.profiles[nr]))
        vl = QgsVectorLayer(type, name, "memory")
        pr = vl.dataProvider()
        vl.startEditing()
        # add fields
        pr.addAttributes([QgsField("Value", QVariant.Double)])
        vl.updateFields()
        # Add features to layer
        for i in range(len(self.profiletoolcore.profiles[nr]["l"])):
            fet = QgsFeature(vl.fields())
            # set geometry
            fet.setGeometry(
                QgsGeometry.fromPointXY(
                    QgsPointXY(
                        self.profiletoolcore.profiles[nr]["x"][i],
                        self.profiletoolcore.profiles[nr]["y"][i],
                    )
                )
            )
            # set attributes
            fet.setAttributes([self.profiletoolcore.profiles[nr]["z"][i]])
            pr.addFeatures([fet])
        vl.commitChanges()
        # labeling/enabled
        if False:
            labelsettings = vl.labeling().settings()
            labelsettings.enabled = True

        # vl.setCustomProperty("labeling/enabled", "true")
        # show layer
        QgsProject.instance().addMapLayer(vl)

    # ********************************************************************************
    # save drawn line ****************************************************************
    # ********************************************************************************

    def _buildSaveDrawnLineButton(self):
        self.butSaveDrawnLine = QPushButton(self.tr("Save drawn line as layer"))
        self.butSaveDrawnLine.setToolTip(
            self.tr(
                "Save the polyline you just drew (Temporary polyline mode) as a "
                "scratch line layer in the project. Right-click the layer in QGIS "
                "to export it to a file."
            )
        )
        self.butSaveDrawnLine.clicked.connect(self.saveDrawnLineAsLayer)
        layout = self.groupBox.layout()
        if isinstance(layout, QGridLayout):
            layout.addWidget(self.butSaveDrawnLine, 3, 0, 1, 2)
        elif layout is not None:
            layout.addWidget(self.butSaveDrawnLine)

    def saveDrawnLineAsLayer(self):
        points = list(getattr(self.profiletoolcore, "pointstoDraw", None) or [])
        if len(points) < 2:
            self.iface.messageBar().pushMessage(
                "Profile Tool +",
                self.tr("Draw a polyline first (Temporary polyline mode)."),
                level=Qgis.MessageLevel.Info,
            )
            return

        crs_authid = QgsProject.instance().crs().authid() or "EPSG:4326"
        vl = QgsVectorLayer(
            "LineString?crs={}".format(crs_authid),
            "ProfileTool_line",
            "memory",
        )
        pr = vl.dataProvider()
        pr.addAttributes([QgsField("id", QVariant.Int)])
        vl.updateFields()

        feat = QgsFeature(vl.fields())
        feat.setGeometry(
            QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])
        )
        feat.setAttributes([1])
        pr.addFeatures([feat])
        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)

        self.iface.messageBar().pushMessage(
            "Profile Tool +",
            self.tr("Saved drawn line to layer \"{}\".").format(vl.name()),
            level=Qgis.MessageLevel.Success,
        )

    # ********************************************************************************
    # other things ****************************************************************
    # ********************************************************************************

    def closeEvent(self, event):
        self.closed.emit()
        self.profiletoolcore.cleaning()
        # self.butSaveAs.clicked.disconnect(self.saveAs)
        # return QDockWidget.closeEvent(self, event)

    # ********************************************************************************
    # statistics panel ***************************************************************
    # ********************************************************************************

    STATS_ROWS = [
        "Total length (m)",
        "Elevation change (m)",
        "Max elevation (m @ ch)",
        "Min elevation (m @ ch)",
        "Gradient",
        "Equal-area slope (m/km)",
    ]

    # The segment table reports the same metrics as the whole-profile one, so
    # the two read row for row.
    SEGMENT_ROWS = STATS_ROWS

    def _makeStatsTable(self, rows):
        table = QTableWidget(len(rows), 0)
        table.setVerticalHeaderLabels([self.tr(r) for r in rows])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        # Keep the panel usable in the short bottom dock.
        table.verticalHeader().setDefaultSectionSize(20)
        return table

    def _buildStatsPanel(self):
        """Adds the Statistics and Segment boxes to the Profile tab splitter,
        between the plot frame and the layer/options frame."""
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        statsBox = QGroupBox(self.tr("Statistics"))
        statsLayout = QVBoxLayout(statsBox)
        statsLayout.setContentsMargins(4, 4, 4, 4)
        self.statsTable = self._makeStatsTable(self.STATS_ROWS)
        statsLayout.addWidget(self.statsTable)
        vbox.addWidget(statsBox)

        self.segmentBox = QGroupBox(self.tr("Segment"))
        segLayout = QVBoxLayout(self.segmentBox)
        segLayout.setContentsMargins(4, 4, 4, 4)
        self.segmentTable = self._makeStatsTable(self.SEGMENT_ROWS)
        segLayout.addWidget(self.segmentTable)

        buttonRow = QHBoxLayout()
        self.cbMeasureSegment = ToggleSwitch()
        caption = QLabel(self.tr("Measure segment"))
        tip = self.tr(
            "Click the plot to set the segment start, click again to set the end. "
            "PyQtGraph plot library only."
        )
        self.cbMeasureSegment.setToolTip(tip)
        caption.setToolTip(tip)
        self.cbMeasureSegment.toggled.connect(self._onMeasureSegmentToggled)
        buttonRow.addWidget(self.cbMeasureSegment)
        buttonRow.addWidget(caption)
        buttonRow.addStretch(1)
        self.butClearSegment = QPushButton(self.tr("Clear"))
        self.butClearSegment.clicked.connect(self.clearSegment)
        buttonRow.addWidget(self.butClearSegment)
        segLayout.addLayout(buttonRow)
        vbox.addWidget(self.segmentBox)

        self.statsBox = statsBox
        self.statsContainer = container

        # "Show stats" toggle, in the Options box on the right. It hides the
        # whole column - Statistics and Segment both - so the plot gets the space.
        self.cbShowStats = QCheckBox(self.tr("Show stats"))
        self.cbShowStats.setToolTip(
            self.tr("Show the statistics and segment panel next to the plot.")
        )
        self.cbShowStats.setChecked(True)
        self.cbShowStats.toggled.connect(container.setVisible)
        optionsLayout = self.groupBox.layout()
        if isinstance(optionsLayout, QGridLayout):
            optionsLayout.addWidget(self.cbShowStats, 2, 0)
        elif optionsLayout is not None:
            optionsLayout.addWidget(self.cbShowStats)

        # Index 1 puts it after `frame` (plot) and before `frame_2` (layers).
        self.splitter.insertWidget(1, container)
        container.setMinimumWidth(300)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)

    def updateStatsPanel(self):
        """Refreshes the Statistics and Segment panels.

        Never raises: these are read-only summaries, and letting them throw
        would take down whatever called them (plot refresh, mouse tracking...).
        """
        try:
            self._updateStatsPanel()
            self._updateSegmentPanel()
        except Exception as e:  # noqa: BLE001
            QgsMessageLog.logMessage(
                "Statistics panel could not be updated: {}".format(e),
                "ProfileTool",
                Qgis.MessageLevel.Warning,
            )

    def _profileHeaders(self, profiles):
        return [
            p.get("layer").name() if p.get("layer") is not None else str(i + 1)
            for i, p in enumerate(profiles)
        ]

    def _statsValues(self, stats):
        """Formats a compute_stats/segment_stats dict into table cells."""
        if stats is None:
            return ["/"] * len(self.STATS_ROWS)
        eas = stats["eas_m_per_km"]
        return [
            "{:.1f}".format(stats["length"]),
            "{:+.2f}".format(stats["dz"]),
            "{:.2f} @ {:.1f}".format(stats["max_z"], stats["max_at"]),
            "{:.2f} @ {:.1f}".format(stats["min_z"], stats["min_at"]),
            "{:.2f} % ({:.4f} m/m)".format(
                stats["gradient_pct"], stats["gradient_m_per_m"]
            ),
            "/" if eas is None else "{:.2f}".format(eas),
        ]

    def _fillTable(self, table, profiles, values_for):
        table.clearContents()
        table.setColumnCount(len(profiles))
        for col, profile in enumerate(profiles):
            for row, value in enumerate(values_for(profile)):
                table.setItem(row, col, QTableWidgetItem(value))
        table.setHorizontalHeaderLabels(self._profileHeaders(profiles))
        table.resizeColumnsToContents()

    def _updateStatsPanel(self):
        table = getattr(self, "statsTable", None)
        if table is None:
            return
        profiles = getattr(self.profiletoolcore, "profiles", None) or []

        def values_for(profile):
            return self._statsValues(compute_stats(profile.get("l"), profile.get("z")))

        self._fillTable(table, profiles, values_for)

    # ---- segment measurement ----------------------------------------------

    def isMeasuringSegment(self):
        cb = getattr(self, "cbMeasureSegment", None)
        return cb is not None and cb.isChecked()

    def _onMeasureSegmentToggled(self, checked):
        if not checked:
            self.clearSegment()

    def registerSegmentClick(self, x):
        """Called from the plot click handler with a chainage already snapped
        to a profile sample.

        Left click only: the first click sets the start, the second closes the
        segment, and the next starts a new one. Right click is left alone so it
        keeps raising pyqtgraph's own plot menu.
        """
        if x is None:
            return
        if self._segment_start is not None and self._segment_end is None:
            self._segment_end = x
        else:
            self._segment_start = x
            self._segment_end = None
        QgsMessageLog.logMessage(
            "Segment {} set at chainage {}".format(
                "end" if self._segment_end is not None else "start", x
            ),
            "ProfileTool",
            Qgis.MessageLevel.Info,
        )
        self.updateStatsPanel()

    def clearSegment(self):
        self._segment_start = None
        self._segment_end = None
        self.updateStatsPanel()

    def _removeSegmentMarkers(self):
        plotWdg = getattr(self, "plotWdg", None)
        for item in self._segment_items:
            with suppress(Exception):
                plotWdg.removeItem(item)
        self._segment_items = []

    def _drawSegmentMarkers(self):
        """Draws the segment bounds on the plot. PyQtGraph only - the
        Matplotlib backend has no click handling to drive this."""
        self._removeSegmentMarkers()
        if self.TYPE != "PyQtGraph":
            return
        if self._segment_start is None and self._segment_end is None:
            return
        plotWdg = getattr(self, "plotWdg", None)
        if plotWdg is None:
            return

        pen = pg.mkPen((0, 130, 255), width=1, style=Qt.PenStyle.DashLine)
        for x in (self._segment_start, self._segment_end):
            if x is None:
                continue
            line = pg.InfiniteLine(pos=x, angle=90, pen=pen, name="segment_bound")
            plotWdg.addItem(line)
            self._segment_items.append(line)

        if self._segment_start is not None and self._segment_end is not None:
            region = pg.LinearRegionItem(
                values=sorted([self._segment_start, self._segment_end]),
                movable=False,
                brush=(0, 130, 255, 40),
            )
            region.setZValue(-10)
            plotWdg.addItem(region)
            self._segment_items.append(region)

    def _updateSegmentPanel(self):
        table = getattr(self, "segmentTable", None)
        if table is None:
            return

        profiles = getattr(self.profiletoolcore, "profiles", None) or []
        self._drawSegmentMarkers()

        if self._segment_start is None or self._segment_end is None:
            if self._segment_start is None:
                title = self.tr("Segment")
            else:
                title = self.tr("Segment - start {:.1f} m, click the end").format(
                    self._segment_start
                )
            self.segmentBox.setTitle(title)
            table.clearContents()
            table.setColumnCount(0)
            return

        lo, hi = sorted([self._segment_start, self._segment_end])
        self.segmentBox.setTitle(
            self.tr("Segment {:.1f} - {:.1f} m  (length {:.1f} m)").format(
                lo, hi, hi - lo
            )
        )

        def values_for(profile):
            return self._statsValues(
                segment_stats(
                    profile.get("l"),
                    profile.get("z"),
                    self._segment_start,
                    self._segment_end,
                )
            )

        self._fillTable(table, profiles, values_for)

    # generic save as button
    def saveAs(self):
        idx = self.cbxSaveAs.currentText()
        if idx == "Graph - PDF":
            self.outPDF()
        elif idx == "Graph - PNG":
            self.outPNG()
        elif idx == "Graph - SVG":
            self.outSVG()
        elif idx == "Graph - print (PS)":
            self.outPrint()
        elif idx == "3D line - DXF":
            self.outDXF("3D")
        elif idx == "2D Profile - DXF":
            self.outDXF("2D")
        else:
            print("plottingtool: invalid index " + str(idx))

    def outPrint(self):  # Postscript file rendering doesn't work properly yet.
        PlottingTool().outPrint(self.iface, self, self.mdl, self.cboLibrary.currentText())

    def outPDF(self):
        PlottingTool().outPDF(self.iface, self, self.mdl, self.cboLibrary.currentText())

    def outSVG(self):
        PlottingTool().outSVG(self.iface, self, self.mdl, self.cboLibrary.currentText())

    def outPNG(self):
        PlottingTool().outPNG(self.iface, self, self.mdl, self.cboLibrary.currentText())

    def outDXF(self, type):
        PlottingTool().outDXF(
            self.iface,
            self,
            self.mdl,
            self.cboLibrary.currentText(),
            self.profiletoolcore.profiles,
            type,
        )
