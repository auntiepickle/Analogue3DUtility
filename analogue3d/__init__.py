"""Analogue 3D Utility - tools for the Analogue 3D console and its 8BitDo 64 pad.

Run the project via the root launcher: ``python a3d.py``. The package is kept
import-light (this __init__ pulls in nothing heavy) so the launcher can bootstrap
dependencies before any submodule imports requests/psutil/etc.
"""

__version__ = "0.5.1"
