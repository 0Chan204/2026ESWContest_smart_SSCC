"""Allow both `python -m local` and `python local/run.py`."""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local.app import main

if __name__ == "__main__":
    main()
