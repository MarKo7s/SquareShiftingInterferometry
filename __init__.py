"""ModeLab square phase-shifting interferometry on the SLM."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("SquareShiftingInterferometry")
except PackageNotFoundError:
    __version__ = "1.0.0"

from .engine import SquareShifting

__all__ = [
    "SquareShifting",
    "__version__",
]
