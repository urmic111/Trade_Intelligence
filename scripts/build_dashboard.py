#!/usr/bin/env python3
"""
Convert Trade Flow Excel report → CSV, then build Excel dashboard from CSVs.

Usage:
    python scripts/build_dashboard.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.excel_to_csv import CSV_DIR, excel_to_csv
from src.reporting.dashboard import DASHBOARD_PATH, build_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("dashboard_builder")


def main() -> None:
    logger.info("Step 1/2 — Converting Excel workbook to CSV…")
    paths = excel_to_csv()
    logger.info("Wrote %s CSV files to %s", len(paths), CSV_DIR)

    logger.info("Step 2/2 — Building Excel dashboard from CSV inputs…")
    out = build_dashboard(CSV_DIR, DASHBOARD_PATH)
    logger.info("DONE — dashboard: %s", out)


if __name__ == "__main__":
    main()
