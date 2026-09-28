#!/usr/bin/env python3
"""Grab a live Fake/sim GUI screenshot for README (docs/images/gui.png)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DEFAULT = REPO_ROOT / "docs" / "images" / "gui.png"


class _FakeEngine:
    step_px = 50
    square_size_px = 100
    aperture_diameter_mm = 7.5
    running = False
    stop_requested = False

    def view_state(self):
        import numpy as np

        axis = np.arange(-4, 5) * 460.0
        yy, xx = np.mgrid[-4:5, -4:5]
        field = np.exp(1j * (xx / 2.0 + yy / 3.0))
        field[xx**2 + yy**2 > 12] = 0
        record = {
            "field": field,
            "x_um": axis,
            "y_um": axis,
            "finished_at": "2026-09-28T14:05:31+10:00",
        }
        progress = {"iteration": 0, "total": 0, "active_pol": None}
        return {"H": record, "V": dict(record)}, progress, False

    def set_step(self, _step):
        return None

    def set_square_size(self, _size):
        return None

    def set_aperture(self, _diameter):
        return None

    def scan(self, *_args, **_kwargs):
        return False

    def stop(self):
        return None

    def save(self):
        raise RuntimeError("No square-shift scan to save.")


def build_window():
    from SquareShiftingInterferometry.ui import SquareShiftingWidget

    window = SquareShiftingWidget(_FakeEngine())
    window.setWindowTitle("Square Shifting Interferometry")

    def teardown() -> None:
        window.close()

    return window, teardown


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture GUI screenshot for README.")
    parser.add_argument("-o", "--output", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--wait-ms", type=int, default=4000)
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="Use QT_QPA_PLATFORM=offscreen (may blank pyqtgraph on Windows).",
    )
    args = parser.parse_args()

    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication

    pg.setConfigOptions(useOpenGL=False, antialias=True)

    app = QApplication.instance() or QApplication(sys.argv)
    window, teardown = build_window()
    window.resize(780, 1100)
    window.show()
    window.raise_()
    window.activateWindow()

    deadline = time.perf_counter() + max(args.wait_ms, 200) / 1000.0
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pix = window.grab()
    if pix.isNull() or pix.width() < 10:
        teardown()
        raise SystemExit("grab() returned an empty pixmap")
    if not pix.save(str(args.output), "PNG"):
        teardown()
        raise SystemExit(f"Failed to write {args.output}")

    teardown()
    print(f"Wrote {args.output}")
    app.quit()


if __name__ == "__main__":
    main()
