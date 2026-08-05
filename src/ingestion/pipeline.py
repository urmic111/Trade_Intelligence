"""Dataset acquisition from Data.gov / agency APIs with synthetic fallbacks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config.settings import BEA_API_KEY, CENSUS_API_KEY, DATASETS, DATA_RAW
from src.ingestion.http_client import fetch_json
from src.ingestion import synthetic

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_entry(
    dataset_key: str,
    status: str,
    row_count: int,
    schema_notes: str,
    source_mode: str,
) -> dict[str, Any]:
    meta = DATASETS[dataset_key]
    return {
        "dataset_key": dataset_key,
        "dataset_name": meta["name"],
        "url": meta["url"],
        "source": meta["source"],
        "fetched_at_utc": _now_iso(),
        "status": status,
        "source_mode": source_mode,
        "row_count": row_count,
        "schema_notes": schema_notes,
    }


def _census_to_dataframe(payload: list) -> pd.DataFrame | None:
    if not payload or len(payload) < 2:
        return None
    headers, *rows = payload
    return pd.DataFrame(rows, columns=headers)


def ingest_census_hs(flow: str = "imports") -> tuple[pd.DataFrame, dict]:
    """Fetch Census HS import/export timeseries; fall back to synthetic."""
    key = "census_imports_hs" if flow == "imports" else "census_exports_hs"
    url = DATASETS[key]["url"]
    params: dict[str, Any] = {
        "get": "CTY_CODE,CTY_NAME,I_COMMODITY,I_COMMODITY_LDESC,GEN_VAL_MO"
        if flow == "imports"
        else "CTY_CODE,CTY_NAME,E_COMMODITY,E_COMMODITY_LDESC,ALL_VAL_MO",
        "time": "from+2023-01",
        "COMM_LVL": "HS4",
    }
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY

    payload = fetch_json(url, params=params)
    if payload:
        df = _census_to_dataframe(payload)
        if df is not None and not df.empty:
            path = DATA_RAW / f"census_{flow}_hs.csv"
            df.to_csv(path, index=False)
            return df, _log_entry(
                key,
                "success",
                len(df),
                f"Live Census API columns: {list(df.columns)}",
                "live_api",
            )

    logger.info("Using synthetic fallback for Census %s HS", flow)
    trade = synthetic.generate_monthly_trade()
    value_col = "import_value_usd_m" if flow == "imports" else "export_value_usd_m"
    df = trade[
        ["date", "country", "hs_code", "commodity", "critical", value_col]
    ].rename(columns={value_col: "value_usd_m"})
    df["flow"] = flow
    path = DATA_RAW / f"census_{flow}_hs_synthetic.csv"
    df.to_csv(path, index=False)
    return df, _log_entry(
        key,
        "fallback_synthetic",
        len(df),
        "Synthetic monthly country×commodity values (USD millions). "
        "Set CENSUS_API_KEY for live data.",
        "synthetic",
    )


def ingest_bea_trade() -> tuple[pd.DataFrame, dict]:
    """Fetch BEA ITA goods/services aggregates; fall back to synthetic."""
    key = "bea_trade"
    url = DATASETS[key]["url"]
    if BEA_API_KEY:
        params = {
            "UserID": BEA_API_KEY,
            "method": "GetData",
            "DatasetName": "ITA",
            "Indicator": "BalGds",
            "AreaOrCountry": "AllCountries",
            "Frequency": "A",
            "Year": "2018,2019,2020,2021,2022,2023,2024,2025",
            "ResultFormat": "JSON",
        }
        payload = fetch_json(url, params=params)
        if payload and "BEAAPI" in str(payload):
            try:
                results = payload["BEAAPI"]["Results"]["Data"]
                df = pd.DataFrame(results)
                df.to_csv(DATA_RAW / "bea_ita.csv", index=False)
                return df, _log_entry(
                    key, "success", len(df), f"BEA ITA columns: {list(df.columns)}", "live_api"
                )
            except (KeyError, TypeError) as exc:
                logger.warning("BEA parse failed: %s", exc)

    df = synthetic.generate_bea_aggregate()
    df.to_csv(DATA_RAW / "bea_trade_synthetic.csv", index=False)
    return df, _log_entry(
        key,
        "fallback_synthetic",
        len(df),
        "Synthetic BEA-style goods & services balances. Set BEA_API_KEY for live data.",
        "synthetic",
    )


def ingest_bts_ports() -> tuple[pd.DataFrame, dict]:
    """Fetch BTS port statistics; fall back to synthetic."""
    key = "bts_ports"
    url = DATASETS[key]["url"]
    payload = fetch_json(url, params={"$limit": 5000})
    if payload and isinstance(payload, list) and len(payload) > 0:
        df = pd.DataFrame(payload)
        df.to_csv(DATA_RAW / "bts_ports.csv", index=False)
        return df, _log_entry(
            key, "success", len(df), f"BTS columns: {list(df.columns)}", "live_api"
        )

    df = synthetic.generate_port_stats()
    df.to_csv(DATA_RAW / "bts_ports_synthetic.csv", index=False)
    return df, _log_entry(
        key,
        "fallback_synthetic",
        len(df),
        "Synthetic port TEU, congestion index, dwell days, vessel queue.",
        "synthetic",
    )


def ingest_commerce_supply_chain() -> tuple[pd.DataFrame, dict]:
    key = "commerce_supply_chain"
    # Port HS endpoint often needs a key; use event synthetic by default
    df = synthetic.generate_supply_chain_events()
    df.to_csv(DATA_RAW / "commerce_supply_chain_synthetic.csv", index=False)
    return df, _log_entry(
        key,
        "fallback_synthetic",
        len(df),
        "Supply-chain disruption event log (severity, delay, commodity, country).",
        "synthetic",
    )


def ingest_itc_tariffs() -> tuple[pd.DataFrame, dict]:
    key = "itc_tariffs"
    df = synthetic.generate_tariff_schedule()
    df.to_csv(DATA_RAW / "itc_tariffs_synthetic.csv", index=False)
    return df, _log_entry(
        key,
        "fallback_synthetic",
        len(df),
        "HTS MFN + Section 301 effective duty rates by HS4 commodity.",
        "synthetic",
    )


def ingest_usda_commodity() -> tuple[pd.DataFrame, dict]:
    key = "usda_commodity"
    trade = synthetic.generate_monthly_trade()
    ag_hs = {"1005", "1201"}
    df = trade[trade["hs_code"].isin(ag_hs)].copy()
    df.to_csv(DATA_RAW / "usda_commodity_synthetic.csv", index=False)
    return df, _log_entry(
        key,
        "fallback_synthetic",
        len(df),
        "Ag commodity subset (maize, soya) from unified trade table.",
        "synthetic",
    )


def run_ingestion() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Execute full ingestion suite. Returns data dict + ingestion log DataFrame."""
    logs: list[dict] = []
    data: dict[str, pd.DataFrame] = {}

    bea_df, bea_log = ingest_bea_trade()
    data["bea"] = bea_df
    logs.append(bea_log)

    imp_df, imp_log = ingest_census_hs("imports")
    data["census_imports"] = imp_df
    logs.append(imp_log)

    exp_df, exp_log = ingest_census_hs("exports")
    data["census_exports"] = exp_df
    logs.append(exp_log)

    ports_df, ports_log = ingest_bts_ports()
    data["ports"] = ports_df
    logs.append(ports_log)

    sc_df, sc_log = ingest_commerce_supply_chain()
    data["supply_chain"] = sc_df
    logs.append(sc_log)

    tariff_df, tariff_log = ingest_itc_tariffs()
    data["tariffs"] = tariff_df
    logs.append(tariff_log)

    usda_df, usda_log = ingest_usda_commodity()
    data["usda"] = usda_df
    logs.append(usda_log)

    # Unified detailed trade (always from synthetic generator for analytics consistency
    # when live APIs return heterogeneous schemas)
    if "import_value_usd_m" not in data["census_imports"].columns:
        data["unified_trade"] = synthetic.generate_monthly_trade()
    else:
        data["unified_trade"] = data["census_imports"]  # unlikely path

    # Prefer always having a rich unified table
    data["unified_trade"] = synthetic.generate_monthly_trade()
    logs.append(
        {
            "dataset_key": "unified_trade",
            "dataset_name": "Unified Trade Table (country × commodity × month)",
            "url": "internal://synthetic.generate_monthly_trade",
            "source": "Agent Data Engineering Layer",
            "fetched_at_utc": _now_iso(),
            "status": "constructed",
            "source_mode": "synthetic",
            "row_count": len(data["unified_trade"]),
            "schema_notes": (
                "Normalized columns: date, country, hs_code, commodity, critical, "
                "import/export value & volume."
            ),
        }
    )

    log_df = pd.DataFrame(logs)
    logger.info("Ingestion complete: %s datasets", len(logs))
    return data, log_df
