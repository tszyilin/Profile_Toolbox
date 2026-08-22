import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class ProfileTool:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir, 'icons', 'profileIcon.png'))
        self.action = QAction(icon, 'Profile Plot', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu('&Profile Plot', self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu('&Profile Plot', self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() in (self.dialog.draw_tool, self.dialog.pick_tool):
                canvas.unsetMapTool(canvas.mapTool())
            self.dialog.close()
            self.dialog = None

    def run(self):
        from .profile_tool_dialog import ProfileToolDialog
        if self.dialog is None:
            self.dialog = ProfileToolDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
