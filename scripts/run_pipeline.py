#!/usr/bin/env python3
"""
Trade Flow Intelligence Agent — end-to-end pipeline runner.

Usage:
    cd trade_flow_intelligence
    pip install -r requirements.txt
    python scripts/run_pipeline.py

Optional env:
    CENSUS_API_KEY, BEA_API_KEY
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import OUTPUT_WORKBOOK
from src.ingestion.pipeline import run_ingestion
from src.engineering.pipeline import run_engineering
from src.analytics.pipeline import run_analytics
from src.risk.pipeline import run_risk
from src.insights.pipeline import (
    build_visualization_data,
    generate_narrative,
    generate_recommendations,
)
from src.reporting.excel_exporter import export_workbook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("trade_flow_agent")


def evaluate_and_plan(ingestion_log, sheets) -> None:
    """Autonomous loop: quality eval, gaps, next steps."""
    logger.info("=" * 60)
    logger.info("AUTONOMOUS LOOP — Evaluation & Next Iteration Plan")
    logger.info("=" * 60)

    modes = ingestion_log["source_mode"].value_counts().to_dict() if "source_mode" in ingestion_log else {}
    logger.info("Source modes: %s", modes)

    missing_live = ingestion_log.loc[
        ingestion_log["source_mode"] != "live_api", "dataset_name"
    ].tolist() if "source_mode" in ingestion_log else []
    if missing_live:
        logger.info("Datasets not yet live (need API keys / public endpoints):")
        for name in missing_live:
            logger.info("  - %s", name)

    for sheet, df in sheets.items():
        n = 0 if df is None else len(df)
        logger.info("Sheet %-22s rows=%s", sheet, n)

    logger.info("Suggested next steps:")
    logger.info("  1. Export CENSUS_API_KEY / BEA_API_KEY and re-run for live freshness.")
    logger.info("  2. Wire ITC DataWeb bulk HTS download for true duty schedules.")
    logger.info("  3. Add Prophet/LSTM ensemble forecast comparison sheet.")
    logger.info("  4. Schedule cron/Airflow weekly refresh into outputs/.")
    logger.info("  5. Push Critical-tier Risk_Scores to alerting webhook.")


def main() -> Path:
    logger.info("Starting Trade Flow Intelligence Agent pipeline…")

    # 1. Acquisition
    logger.info("[1/5] Data Acquisition")
    raw, ingestion_log = run_ingestion()

    # 2. Engineering
    logger.info("[2/5] Data Engineering")
    cleaned, clean_summary = run_engineering(raw)

    # 3. Analytics
    logger.info("[3/5] Analytics & Modeling")
    analytics = run_analytics(cleaned)

    # 4. Risk
    logger.info("[4/5] Risk & Insight Generation")
    risk = run_risk(cleaned, analytics)
    narrative = generate_narrative(
        ingestion_log,
        analytics["anomalies"],
        analytics["forecasts"],
        risk["risk_scores"],
        risk["port_risk"],
        analytics["clusters"],
    )
    recommendations = generate_recommendations(
        risk["risk_scores"], risk["port_risk"], analytics["anomalies"]
    )
    viz = build_visualization_data(
        cleaned["commodity_ts"],
        analytics["forecasts"],
        risk["risk_scores"],
        risk["port_risk"],
        analytics["dependency"],
    )

    # 5. Excel reporting
    logger.info("[5/5] Excel Reporting")
    sheets = {
        "Data_Ingestion_Log": ingestion_log,
        "Cleaned_Data_Summary": clean_summary,
        "Anomalies": analytics["anomalies"],
        "Forecasts": analytics["forecasts"],
        "Clusters": analytics["clusters"],
        "Risk_Scores": risk["risk_scores"],
        "Insights_Narrative": narrative,
        "Recommendations": recommendations,
        "Visualizations_Data": viz,
        "Port_Risk": risk["port_risk"],
        "Dependency_Detail": analytics["dependency"],
    }
    out = export_workbook(sheets, OUTPUT_WORKBOOK)

    evaluate_and_plan(ingestion_log, sheets)
    logger.info("DONE — workbook: %s", out)
    return out


if __name__ == "__main__":
    main()
