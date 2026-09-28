"""Aperture grid for the square piston scan. No hardware and no Qt."""

import numpy as np


def make_probe_grid(mask_size, pixel_size_mm, aperture_diameter_mm, step_px):
    """Downsampled centers inside the aperture, in the notebook's order.

    ``centers_x`` and ``centers_y`` are full-mask pixel indices. ``rows`` and
    ``cols`` are ``np.nonzero`` of the downsampled mask, which is the same
    order, so a result can be written at ``field[row, col]``.
    """
    size = int(mask_size)
    step = int(step_px)
    pixel = float(pixel_size_mm)
    diameter = float(aperture_diameter_mm)
    if size < 1:
        raise ValueError("mask_size must be positive")
    if step < 1:
        raise ValueError("step_px must be a positive integer")
    if pixel <= 0:
        raise ValueError("pixel_size_mm must be positive")
    if diameter <= 0:
        raise ValueError("aperture_diameter_mm must be positive")

    index = np.arange(size)
    x_mm = (index - size // 2) * pixel
    x_grid, y_grid = np.meshgrid(x_mm, x_mm)
    x_idx, y_idx = np.meshgrid(index, index)
    inside = np.hypot(x_grid, y_grid) < (diameter / 2.0)

    mask = inside[::step, ::step]
    rows, cols = np.nonzero(mask)
    x_px = index[::step]
    x_mm_down = x_mm[::step]
    return {
        "mask": mask,
        "rows": rows,
        "cols": cols,
        "centers_x": x_idx[::step, ::step][mask],
        "centers_y": y_idx[::step, ::step][mask],
        "x_px": x_px,
        "y_px": np.array(x_px, copy=True),
        "x_mm": x_mm_down,
        "y_mm": np.array(x_mm_down, copy=True),
        "x_um": x_mm_down * 1e3,
        "y_um": np.array(x_mm_down, copy=True) * 1e3,
    }


def piston_window(cx, cy, hologram, window_size, phi):
    """Clear ``hologram`` and add ``phi`` in a square around one pixel center."""
    crop = int(window_size) // 2
    hologram *= 0
    hologram[cy - crop:cy + crop + 1, cx - crop:cx + crop + 1] += phi
    return hologram


def fringe_sample(power):
    """Phase and amplitude from the first ``rfft`` bin, as in the notebook."""
    spectrum = np.fft.rfft(np.asarray(power, dtype=float))
    return float(np.angle(spectrum[1])), float(np.abs(spectrum[1]))


def pixel_edges(axis_um):
    """Half-pixel edges so sample coordinates sit on pixel centers."""
    axis = np.asarray(axis_um, dtype=float)
    if axis.size == 0:
        raise ValueError("scan axis is empty")
    if axis.size == 1:
        step = 1.0
    else:
        step = float(axis[1] - axis[0])
    return float(axis[0] - step / 2.0), float(axis[-1] + step / 2.0)
