#!/usr/bin/env python3
"""Build Tableau dashboard (.twb / .twbx) from pipeline CSV exports."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tableau.workbook_builder import TABLEAU_DIR, TWBX_PATH, build

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("tableau_builder")


def main() -> None:
    out = build()
    logger.info("Tableau assets: %s", TABLEAU_DIR)
    logger.info("Open in Tableau Public/Desktop: %s", out)


if __name__ == "__main__":
    main()
