"""Convert multi-sheet Excel workbook to individual CSV files."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config.settings import OUTPUTS, OUTPUT_WORKBOOK

logger = logging.getLogger(__name__)

CSV_DIR = OUTPUTS / "csv"


def excel_to_csv(
    workbook: Path | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    """
    Read each sheet from the Trade Flow workbook and write a CSV per sheet.

    Returns list of written CSV paths.
    """
    wb_path = Path(workbook) if workbook else OUTPUT_WORKBOOK
    dest = Path(out_dir) if out_dir else CSV_DIR
    dest.mkdir(parents=True, exist_ok=True)

    if not wb_path.exists():
        raise FileNotFoundError(f"Workbook not found: {wb_path}")

    sheets = pd.read_excel(wb_path, sheet_name=None, engine="openpyxl")
    written: list[Path] = []
    for name, df in sheets.items():
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        path = dest / f"{safe}.csv"
        df.to_csv(path, index=False)
        written.append(path)
        logger.info("Wrote %s (%s rows)", path.name, len(df))

    # Manifest for dashboard consumers
    manifest = dest / "_manifest.csv"
    pd.DataFrame(
        {
            "sheet": list(sheets.keys()),
            "csv_file": [p.name for p in written],
            "rows": [len(df) for df in sheets.values()],
            "columns": [",".join(map(str, df.columns)) for df in sheets.values()],
        }
    ).to_csv(manifest, index=False)
    written.append(manifest)
    logger.info("Converted %s sheets → %s", len(sheets), dest)
    return written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    excel_to_csv()
