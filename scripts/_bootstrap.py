"""Make the repository root importable when scripts are run as ``python scripts/<name>.py``.

The scripts directory itself is removed from ``sys.path`` so that ``scripts/statistics.py`` can never shadow the
standard-library ``statistics`` module.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve().as_posix() != Path(_SCRIPTS).as_posix()]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
