"""Threaded square phase-shifting scan. Talks to the SLM and power meter only."""

import json
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread

import numpy as np

from .grid import fringe_sample, make_probe_grid, piston_window, pixel_edges

_POLS = ("H", "V", "HV")
_PHASE_STEPS = 5
_SAVE_PATH_ERROR = "Provide a path to save() or call set_saving_path() first."


def _now():
    return datetime.now().astimezone().replace(microsecond=0)


class SquareShifting:
    """Probe the SLM with a square piston and store the coarse complex field.

    ``slm_widget``, ``zernike_widget``, and ``powermeter_widget`` are optional.
    When all three are passed, ``scan`` locks them and the thread unlocks them
    when it finishes. With none of them, the hardware loop and ``stop`` still run.
    """

    def __init__(
        self,
        slm,
        powermeter,
        slm_widget=None,
        zernike_widget=None,
        powermeter_widget=None,
        mask_size=960,
        pixel_size_mm=9.2e-3,
        aperture_diameter_mm=7.5,
        square_size_px=100,
        step_px=50,
    ):
        self.slm = slm
        self.powermeter = powermeter
        self.slm_widget = slm_widget
        self.zernike_widget = zernike_widget
        self.powermeter_widget = powermeter_widget
        self.slm_delay = 0.2

        self.mask_size = int(mask_size)
        self.pixel_size_mm = float(pixel_size_mm)
        self.aperture_diameter_mm = float(aperture_diameter_mm)
        self.square_size_px = int(square_size_px)
        self.step_px = int(step_px)
        self._check_geometry()

        self.fields = {}
        self.progress = {"iteration": 0, "total": 0, "active_pol": None}
        self._saving_path = None
        self._stop = False
        self._starting = False
        self._thread = None
        self._lock = Lock()

    @property
    def running(self):
        thread = self._thread
        return self._starting or (thread is not None and thread.is_alive())

    def set_square_size(self, square_size_px):
        """Square window in pixels. A running scan keeps the size it started with."""
        self._require_idle()
        self.square_size_px = int(square_size_px)
        self._check_geometry()

    def set_step(self, step_px):
        """Spacing between probe centers, in pixels."""
        self._require_idle()
        self.step_px = int(step_px)
        self._check_geometry()

    def set_aperture(self, aperture_diameter_mm):
        """Aperture diameter in millimetres. The radius is half of this."""
        self._require_idle()
        self.aperture_diameter_mm = float(aperture_diameter_mm)
        self._check_geometry()

    def set_saving_path(self, path):
        """Parent directory for later ``save()`` calls."""
        self._saving_path = Path(path)

    def scan(self, pol, on_sample=None, on_finished=None):
        """Start one scan on a daemon thread. Return False if one is already running."""
        if pol not in _POLS:
            raise ValueError(f"Invalid polarization: {pol}")
        with self._lock:
            if self.running:
                return False
            self._starting = True
        try:
            grid = self._snapshot_grid()
            self._stop = False
            n_centers = int(grid["rows"].size)
            with self._lock:
                self.progress = {
                    "iteration": 0,
                    "total": n_centers * _PHASE_STEPS * len(pol),
                    "active_pol": None,
                }
            self.pre_scan_routine()
            self._thread = Thread(
                target=self._scan_thread,
                args=(pol, grid, on_sample, on_finished),
                daemon=True,
            )
            self._thread.start()
            return True
        finally:
            self._starting = False

    def stop(self):
        """Ask the running scan to finish the current phase step and then return."""
        self._stop = True

    @property
    def stop_requested(self):
        return self._stop

    def view_state(self):
        """Copies of the complex fields and progress for a GUI timer."""
        with self._lock:
            fields = {}
            for pol, record in self.fields.items():
                fields[pol] = {
                    "field": np.array(record["field"], copy=True),
                    "x_um": np.array(record["x_um"], copy=True),
                    "y_um": np.array(record["y_um"], copy=True),
                    "finished_at": record["finished_at"],
                }
            progress = dict(self.progress)
        return fields, progress, self.running

    def save(self, path=None):
        """Write one new folder of npz, JSON, and png files. Return that folder."""
        if self.running:
            raise RuntimeError("A square-shift scan is running. Save when it has finished.")

        parent = self._parent_directory(path)
        with self._lock:
            records = {pol: _copy_record(record) for pol, record in self.fields.items()}
        if not records:
            raise RuntimeError("No square-shift scan to save.")

        when = _now()
        folder = parent / f"square_shift_{when.strftime('%Y-%m-%d_%H%M%S')}"
        if folder.exists():
            folder = parent / f"{folder.name}_{when.strftime('%f')}"
        folder.mkdir(parents=True, exist_ok=False)
        _write_json(folder / "scan.json", records, when)
        for pol, record in records.items():
            _write_pol(folder, pol, record)
        return folder

    def pre_scan_routine(self):
        """Lock the instrument panels. No-op when they were not passed in."""
        if not self._panels_connected():
            return
        self.slm_widget.disable_user_interface()
        self.zernike_widget.setEnabled(False)
        self.powermeter_widget.reset_extrema()
        self.powermeter_widget.remote()

    def post_scan_routine(self):
        """Unlock the instrument panels from the worker thread."""
        if not self._panels_connected():
            return
        self.slm_widget.enable_user_interface(run_async=True)
        self.zernike_widget.enable_user_interface(True, run_async=True)
        self.powermeter_widget.start(run_async=True)

    def _panels_connected(self):
        return (
            self.slm_widget is not None
            and self.zernike_widget is not None
            and self.powermeter_widget is not None
        )

    def _require_idle(self):
        if self.running:
            raise RuntimeError("A square-shift scan is running.")

    def _check_geometry(self):
        if self.mask_size < 1:
            raise ValueError("mask_size must be positive")
        if self.step_px < 1:
            raise ValueError("step_px must be a positive integer")
        if self.square_size_px < 1:
            raise ValueError("square_size_px must be a positive integer")
        if self.pixel_size_mm <= 0:
            raise ValueError("pixel_size_mm must be positive")
        if self.aperture_diameter_mm <= 0:
            raise ValueError("aperture_diameter_mm must be positive")

    def _parent_directory(self, path):
        if path is not None:
            return Path(path)
        if self._saving_path is not None:
            return self._saving_path
        raise RuntimeError(_SAVE_PATH_ERROR)

    def _snapshot_grid(self):
        grid = make_probe_grid(
            self.mask_size,
            self.pixel_size_mm,
            self.aperture_diameter_mm,
            self.step_px,
        )
        grid["square_size_px"] = self.square_size_px
        grid["step_px"] = self.step_px
        grid["aperture_diameter_mm"] = self.aperture_diameter_mm
        grid["mask_size"] = self.mask_size
        grid["pixel_size_mm"] = self.pixel_size_mm
        return grid

    def _scan_thread(self, pol, grid, on_sample, on_finished):
        try:
            for target_pol in pol:
                if self._stop:
                    break
                self._scan_polarization(target_pol, grid, on_sample)
        finally:
            with self._lock:
                self.progress["active_pol"] = None
            self.post_scan_routine()
            if on_finished is not None:
                on_finished()

    def _scan_polarization(self, pol, grid, on_sample):
        field = np.zeros(grid["mask"].shape, dtype=complex)
        record = {
            "field": field,
            "mask": grid["mask"],
            "x_px": grid["x_px"],
            "y_px": grid["y_px"],
            "x_mm": grid["x_mm"],
            "y_mm": grid["y_mm"],
            "x_um": grid["x_um"],
            "y_um": grid["y_um"],
            "finished_at": None,
            "step_px": grid["step_px"],
            "square_size_px": grid["square_size_px"],
            "aperture_diameter_mm": grid["aperture_diameter_mm"],
            "mask_size": grid["mask_size"],
            "pixel_size_mm": grid["pixel_size_mm"],
        }
        with self._lock:
            self.fields[pol] = record
            self.progress["active_pol"] = pol

        side = self.slm.ModMuxMask.H if pol == "H" else self.slm.ModMuxMask.V
        side.pattern_enabled = True
        hologram = np.zeros((grid["mask_size"], grid["mask_size"]), dtype=float)
        phases = np.arange(_PHASE_STEPS) / _PHASE_STEPS * 2.0 * np.pi
        try:
            for row, col, cx, cy in zip(
                grid["rows"], grid["cols"], grid["centers_x"], grid["centers_y"]
            ):
                if self._stop:
                    break
                sample = self._measure_center(pol, side, hologram, int(cx), int(cy), phases, grid, on_sample)
                if sample is None:
                    break
                with self._lock:
                    field[int(row), int(col)] = sample
        finally:
            side.pattern[:] = 0
            self.slm.setmask(pol=pol)

        with self._lock:
            record["finished_at"] = _now().isoformat(timespec="seconds")

    def _measure_center(self, pol, side, hologram, cx, cy, phases, grid, on_sample):
        import time

        power = np.empty(_PHASE_STEPS, dtype=float)
        for index, phi in enumerate(phases):
            if self._stop:
                return None
            piston_window(cx, cy, hologram, grid["square_size_px"], float(phi))
            side.pattern = hologram
            self.slm.setmask(pol=pol)
            time.sleep(self.slm_delay)
            measured = float(self.powermeter.meas_power())
            power[index] = measured
            if self.powermeter_widget is not None:
                self.powermeter_widget.feed(measured)
            with self._lock:
                self.progress["iteration"] += 1
            if on_sample is not None:
                on_sample(measured)

        phase, amplitude = fringe_sample(power)
        return amplitude * np.exp(1j * phase)


def _copy_record(record):
    copied = dict(record)
    for key in ("field", "mask", "x_px", "y_px", "x_mm", "y_mm", "x_um", "y_um"):
        copied[key] = np.array(record[key], copy=True)
    return copied


def _write_json(path, records, when):
    payload = {
        "n_phase_steps": _PHASE_STEPS,
        "saved_at": when.isoformat(timespec="seconds"),
        "scans": {},
    }
    for pol, record in records.items():
        payload["scans"][pol] = {
            "step_px": int(record["step_px"]),
            "square_size_px": int(record["square_size_px"]),
            "aperture_diameter_mm": record["aperture_diameter_mm"],
            "mask_size": int(record["mask_size"]),
            "pixel_size_mm": record["pixel_size_mm"],
            "finished_at": record["finished_at"],
        }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _write_pol(folder, pol, record):
    np.savez(
        folder / f"{pol}_field.npz",
        field=record["field"],
        mask=record["mask"],
        x_px=record["x_px"],
        y_px=record["y_px"],
        x_mm=record["x_mm"],
        y_mm=record["y_mm"],
    )
    _write_png(folder / f"{pol}_field.png", pol, record)


def _write_png(path, pol, record):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from visualization import complexToRGB

    field = np.asarray(record["field"])
    x0, x1 = pixel_edges(record["x_um"])
    y0, y1 = pixel_edges(record["y_um"])
    if field.size and np.max(np.abs(field)) > 0:
        image = complexToRGB(field)
    else:
        image = np.zeros(field.shape + (3,), dtype=float)

    figure = Figure(figsize=(5.2, 4.4), dpi=120)
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)
    axes.imshow(image, origin="lower", extent=(x0, x1, y0, y1), aspect="equal")
    axes.set_xlabel("x (um)")
    axes.set_ylabel("y (um)")
    axes.set_title(pol)
    figure.tight_layout()
    figure.savefig(path)
