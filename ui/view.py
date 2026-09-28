"""One complex-field map. This widget does not know the scan engine."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QVBoxLayout, QWidget

from visualization import complexToRGB

from ..grid import pixel_edges


class FieldMapView(QWidget):
    """Complex field on micrometre axes. No colorbar."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._title = title
        self._extent_key = None

        pg.setConfigOptions(useOpenGL=False, antialias=False)
        self._graphics = pg.GraphicsLayoutWidget()
        self._plot = self._graphics.addPlot(row=0, col=0, title=title)
        self._plot.setLabel("bottom", "x", units="um")
        self._plot.setLabel("left", "y", units="um")
        self._plot.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot.getAxis("left").enableAutoSIPrefix(False)
        self._plot.setAspectLocked(True)
        self._plot.showGrid(x=False, y=False)

        self._image = pg.ImageItem(axisOrder="row-major")
        self._plot.addItem(self._image)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics)

    def set_caption(self, text):
        self._plot.setTitle(text)

    def set_field(self, field, x_um, y_um):
        """Draw ``field``. An all-zero map stays black."""
        values = np.asarray(field)
        shown = _field_rgb(values)
        self._image.setImage(shown)

        x0, x1 = pixel_edges(x_um)
        y0, y1 = pixel_edges(y_um)
        self._image.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))

        extent_key = (float(x0), float(x1), float(y0), float(y1), shown.shape)
        if extent_key != self._extent_key:
            self._extent_key = extent_key
            self._plot.autoRange()


def _field_rgb(field):
    if field.size == 0 or np.max(np.abs(field)) == 0:
        return np.zeros(field.shape + (3,), dtype=np.uint8)
    rgb = np.clip(complexToRGB(field) * 255.0, 0, 255)
    return rgb.astype(np.uint8)
