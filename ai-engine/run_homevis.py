"""Start every configured HomeVIS loop; stop with Ctrl+C (no default time limit).

Run: python run_homevis.py
Offline simulation: python run_homevis.py --mode mock
Relative config, .env and data paths are resolved from this project directory.
"""
import os
from pathlib import Path

from src.integration.__main__ import main


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    raise SystemExit(main())
