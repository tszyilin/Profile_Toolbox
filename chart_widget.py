from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel

try:
    import matplotlib
    try:
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    except ImportError:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    from matplotlib.transforms import blended_transform_factory
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class ProfileChartWidget(QWidget):
    """Embeds a matplotlib chart of distance-vs-elevation samples, with a
    crosshair readout fed back to the dialog via `mouse_move_callback`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mouse_move_callback = None
        self.click_callback = None
        self.show_cursor = True
        self._series = []
        self._crosshair_v = None
        self._crosshair_h = None
        self._crosshair_xtext = None
        self._crosshair_ytext = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not MATPLOTLIB_AVAILABLE:
            layout.addWidget(QLabel(
                'matplotlib is not available in this QGIS Python environment '
                '— install it to see the profile chart.'
            ))
            self.figure = None
            self.canvas = None
            self.axes = None
            return

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_xlabel('Distance (m)')
        self.axes.set_ylabel('Elevation')
        self.axes.grid(True, linewidth=0.5, color='lightgray')
        layout.addWidget(self.canvas)

        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.mpl_connect('axes_leave_event', self._on_mouse_leave)
        self.canvas.mpl_connect('button_press_event', self._on_click)

    # ---- data -----------------------------------------------------------

    def set_data(self, series, y_label='Elevation'):
        """series is a list of (label, samples, color) tuples, where samples
        is a list of (distance, elevation, is_valid) and color may be None
        to auto-assign from the matplotlib color cycle. Always drawn as a
        continuous line tracing the terrain (no disconnected-dots mode)."""
        if not MATPLOTLIB_AVAILABLE:
            return
        self._series = series
        self.axes.clear()
        self.axes.set_xlabel('Distance (m)')
        self.axes.set_ylabel(y_label)
        self.axes.grid(True, linewidth=0.5, color='lightgray')

        cycle_colors = matplotlib.rcParams['axes.prop_cycle'].by_key()['color']

        for i, (label, samples, color) in enumerate(series):
            if color is None:
                color = cycle_colors[i % len(cycle_colors)] if len(series) > 1 else 'firebrick'
            label_used = False
            run_x, run_y = [], []
            for distance, elevation, is_valid in samples:
                if is_valid:
                    run_x.append(distance)
                    run_y.append(elevation)
                else:
                    if len(run_x) >= 2:
                        self._plot_run(run_x, run_y, color, label if not label_used else None)
                        label_used = True
                    run_x, run_y = [], []
            if len(run_x) >= 2:
                self._plot_run(run_x, run_y, color, label if not label_used else None)

        if len(series) > 1:
            self.axes.legend()

        self._init_crosshair()
        self.canvas.draw_idle()

    def _plot_run(self, x, y, color, label=None):
        self.axes.plot(x, y, '-', color=color, linewidth=1.2, label=label)

    def set_y_range(self, y_min, y_max):
        if not MATPLOTLIB_AVAILABLE or y_min is None or y_max is None or y_min >= y_max:
            return
        self.axes.set_ylim(y_min, y_max)
        self.canvas.draw_idle()

    def reset_view(self):
        if not MATPLOTLIB_AVAILABLE:
            return
        self.axes.relim()
        self.axes.autoscale()
        self.canvas.draw_idle()

    def save_figure(self, path, fmt=None):
        if not MATPLOTLIB_AVAILABLE:
            return
        self.figure.savefig(path, format=fmt)

    # ---- crosshair --------------------------------------------------------

    def _init_crosshair(self):
        """(Re)create the crosshair artists; set_data's axes.clear() wipes
        out any previous ones, so this is called after every redraw."""
        self._crosshair_v = self.axes.axvline(color='black', linewidth=1, visible=False)
        self._crosshair_h = self.axes.axhline(color='red', linewidth=1, visible=False)
        self._crosshair_xtext = self.axes.text(
            0, 0.02, '', transform=blended_transform_factory(self.axes.transData, self.axes.transAxes),
            va='bottom', ha='left', fontsize=8,
            bbox=dict(boxstyle='round', fc='white', ec='black', alpha=0.85), visible=False,
        )
        self._crosshair_ytext = self.axes.text(
            0.02, 0, '', transform=blended_transform_factory(self.axes.transAxes, self.axes.transData),
            va='bottom', ha='left', fontsize=8,
            bbox=dict(boxstyle='round', fc='white', ec='black', alpha=0.85), visible=False,
        )

    def hide_crosshair(self):
        for artist in (self._crosshair_v, self._crosshair_h, self._crosshair_xtext, self._crosshair_ytext):
            if artist is not None:
                artist.set_visible(False)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _update_crosshair(self, x, y):
        if self._crosshair_v is None:
            return
        self._crosshair_v.set_xdata([x, x])
        self._crosshair_v.set_visible(True)
        self._crosshair_h.set_ydata([y, y])
        self._crosshair_h.set_visible(True)
        self._crosshair_xtext.set_position((x, 0.02))
        self._crosshair_xtext.set_text(f'X : {x:.3f}')
        self._crosshair_xtext.set_visible(True)
        self._crosshair_ytext.set_position((0.02, y))
        self._crosshair_ytext.set_text(f'Y : {y:.3f}')
        self._crosshair_ytext.set_visible(True)
        self.canvas.draw_idle()

    def _on_mouse_move(self, event):
        if event.xdata is None or event.ydata is None:
            self.hide_crosshair()
            if self.mouse_move_callback is not None:
                self.mouse_move_callback(None, None)
            return
        if self.show_cursor:
            self._update_crosshair(event.xdata, event.ydata)
        if self.mouse_move_callback is not None:
            self.mouse_move_callback(event.xdata, event.ydata)

    def _on_mouse_leave(self, event):
        self.hide_crosshair()
        if self.mouse_move_callback is not None:
            self.mouse_move_callback(None, None)

    def _on_click(self, event):
        if self.click_callback is not None:
            self.click_callback(event.xdata, event.ydata)
