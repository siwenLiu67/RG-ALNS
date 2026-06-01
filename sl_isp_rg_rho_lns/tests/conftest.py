"""Test configuration."""

import sys
from pathlib import Path

# Ensure the src directory is importable
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
