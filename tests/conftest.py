from __future__ import annotations

import sys
from pathlib import Path

AMP_ROOT = Path(__file__).resolve().parent.parent / "amp"
if str(AMP_ROOT) not in sys.path:
    sys.path.insert(0, str(AMP_ROOT))
