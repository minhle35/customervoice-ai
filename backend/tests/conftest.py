import sys
from pathlib import Path

# Add project root and backend/ to sys.path so both `app.*` and `pipelines.*` resolve
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
