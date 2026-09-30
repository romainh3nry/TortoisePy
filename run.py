#!/usr/bin/env python3
"""Lanceur de développement — équivalent de la commande `topy`.

Utile avant `pip install -e .`, qui installe `topy` dans le PATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from tortoisepy.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
