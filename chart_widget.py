from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel

try:
    import matplotlib
    try:
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    except ImportError:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class ProfileChartWidget(QWidget):
    """Embeds a matplotlib chart of distance-vs-elevation samples, with a
    crosshair readout fed back to the dialog via `mouse_move_callback`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mouse_move_callback = None
        self._series = []

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
        layout.addWidget(self.canvas)

        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.mpl_connect('axes_leave_event', self._on_mouse_leave)

    # ---- data -----------------------------------------------------------

    def set_data(self, series, interpolated=True):
        """series is a list of (label, samples, color) tuples, where samples
        is a list of (distance, elevation, is_valid) and color may be None
        to auto-assign from the matplotlib color cycle."""
        if not MATPLOTLIB_AVAILABLE:
            return
        self._series = series
        self.axes.clear()
        self.axes.set_xlabel('Distance (m)')
        self.axes.set_ylabel('Elevation')

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
                        self._plot_run(run_x, run_y, interpolated, color, label if not label_used else None)
                        label_used = True
                    run_x, run_y = [], []
            if len(run_x) >= 2:
                self._plot_run(run_x, run_y, interpolated, color, label if not label_used else None)

        if len(series) > 1:
            self.axes.legend()

        self.canvas.draw_idle()

    def _plot_run(self, x, y, interpolated, color, label=None):
        style = '-' if interpolated else 'o'
        self.axes.plot(x, y, style, color=color, linewidth=1.2, markersize=3, label=label)

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

    def _on_mouse_move(self, event):
        if event.xdata is None or event.ydata is None:
            return
        if self.mouse_move_callback is not None:
            self.mouse_move_callback(event.xdata, event.ydata)

    def _on_mouse_leave(self, event):
        if self.mouse_move_callback is not None:
            self.mouse_move_callback(None, None)
