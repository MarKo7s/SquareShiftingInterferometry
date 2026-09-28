"""Controls for SquareShifting. The engine stays free of Qt."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .view import FieldMapView


def _clock(stamp):
    """``2026-09-28T14:05:31+10:00`` to ``2026-09-28 14:05:31``."""
    if not stamp:
        return ""
    return stamp[:19].replace("T", " ")


class SquareShiftingWidget(QWidget):
    """Scan window and the H and V complex-field maps."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _build_ui(self):
        self.setWindowTitle("Square Shifting Interferometry")
        self.resize(780, 1100)

        self._pol_h = QCheckBox("H")
        self._pol_v = QCheckBox("V")
        self._pol_h.setChecked(True)
        self._pol_v.setChecked(True)
        pol_box = QGroupBox("Polarization")
        pol_layout = QVBoxLayout(pol_box)
        pol_layout.addWidget(self._pol_h)
        pol_layout.addWidget(self._pol_v)

        self._step = self._int_spin(self._engine.step_px, 1, 960, " px")
        self._square = self._int_spin(self._engine.square_size_px, 1, 960, " px")
        probe_box = QGroupBox("Probe")
        probe_layout = QVBoxLayout(probe_box)
        probe_layout.addWidget(QLabel("Step"))
        probe_layout.addWidget(self._step)
        probe_layout.addWidget(QLabel("Square size"))
        probe_layout.addWidget(self._square)

        self._aperture = self._float_spin(
            self._engine.aperture_diameter_mm, 0.1, 50.0, 0.1, 2, " mm"
        )
        aperture_box = QGroupBox("Aperture")
        aperture_layout = QVBoxLayout(aperture_box)
        aperture_layout.addWidget(QLabel("Diameter"))
        aperture_layout.addWidget(self._aperture)

        self._input_boxes = (pol_box, probe_box, aperture_box)

        self._scan_button = QPushButton("Start Square Shift")
        self._scan_button.clicked.connect(self._on_scan_button)
        self._save_button = QPushButton("Save")
        self._save_button.clicked.connect(self._on_save)
        buttons = QVBoxLayout()
        buttons.addWidget(self._scan_button)
        buttons.addWidget(self._save_button)
        buttons.addStretch(1)

        options = QHBoxLayout()
        options.addWidget(pol_box)
        options.addWidget(probe_box)
        options.addWidget(aperture_box)
        options.addLayout(buttons)
        options.addStretch(1)

        self._view_h = FieldMapView("H")
        self._view_v = FieldMapView("V")
        maps = QVBoxLayout()
        maps.addWidget(self._view_h, stretch=1)
        maps.addWidget(self._view_v, stretch=1)

        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m")
        self._status = QLabel("idle")

        layout = QVBoxLayout(self)
        layout.addLayout(options)
        layout.addLayout(maps, stretch=1)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)

    @staticmethod
    def _int_spin(value, low, high, suffix):
        box = QSpinBox()
        box.setRange(low, high)
        box.setSuffix(suffix)
        box.setValue(int(value))
        return box

    @staticmethod
    def _float_spin(value, low, high, step, decimals, suffix):
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        box.setValue(value)
        return box

    def _selected_pol(self):
        h_on = self._pol_h.isChecked()
        v_on = self._pol_v.isChecked()
        if h_on and v_on:
            return "HV"
        if h_on:
            return "H"
        if v_on:
            return "V"
        return None

    def _on_scan_button(self):
        if self._engine.running:
            self._engine.stop()
            return

        pol = self._selected_pol()
        if pol is None:
            return

        self._engine.set_step(self._step.value())
        self._engine.set_square_size(self._square.value())
        self._engine.set_aperture(self._aperture.value())
        self._engine.scan(pol)

    def _on_save(self):
        try:
            folder = self._engine.save()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Square Shifting Interferometry", str(exc))
            return
        self._status.setText(f"Saved {folder}")

    def _refresh(self):
        fields, progress, running = self._engine.view_state()
        self._apply_busy(running)
        self._show_progress(progress, running)
        self._show_field(self._view_h, "H", fields.get("H"))
        self._show_field(self._view_v, "V", fields.get("V"))

    def _apply_busy(self, busy):
        for box in self._input_boxes:
            box.setEnabled(not busy)
        self._save_button.setEnabled(not busy)
        if busy:
            self._scan_button.setText("Stop Square Shift")
        else:
            self._scan_button.setText("Start Square Shift")

    def _show_progress(self, progress, busy):
        total = int(progress["total"])
        iteration = int(progress["iteration"])
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(min(iteration, max(total, 1)))
        if self._status.text().startswith("Saved") and not busy:
            return
        pol = progress["active_pol"] or ""
        if busy:
            state = "stopping" if self._engine.stop_requested else "scanning"
            self._status.setText(f"{state}  {pol}  {iteration} / {total}".strip())
        elif total:
            self._status.setText(f"idle  {iteration} / {total}")
        else:
            self._status.setText("idle")

    @staticmethod
    def _show_field(view, pol, record):
        if record is None:
            view.set_caption(pol)
            return
        when = _clock(record["finished_at"])
        if when:
            view.set_caption(f"{pol}  {when}")
        else:
            view.set_caption(pol)
        view.set_field(record["field"], record["x_um"], record["y_um"])
