import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Tests never call the model and never touch the real runtime database.
os.environ.setdefault("EMPOWER_RUNTIME_DIR", str(ROOT / "data" / "runtime" / "test"))
