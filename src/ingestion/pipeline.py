"""Dataset acquisition from Data.gov / agency APIs with synthetic fallbacks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config.settings import BEA_API_KEY, CENSUS_API_KEY, COMMODITIES, DATASETS, DATA_RAW
from src.ingestion.http_client import fetch_json, fetch_response
from src.ingestion import synthetic

logger = logging.getLogger(__name__)

# Target HS4 codes used across analytics (keeps Census payloads bounded)
_TARGET_HS4 = [c["hs"] for c in COMMODITIES]
_HS_NAME = {c["hs"]: c["name"] for c in COMMODITIES}
_HS_CRITICAL = {c["hs"]: c["critical"] for c in COMMODITIES}


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
    if not payload or not isinstance(payload, list) or len(payload) < 2:
        return None
    headers, *rows = payload
    if not isinstance(headers, list):
        return None
    # Census echoes filter predicates (e.g. I_COMMODITY appears twice)
    seen: dict[str, int] = {}
    uniq_headers: list[str] = []
    for h in headers:
        name = str(h)
        if name in seen:
            seen[name] += 1
            uniq_headers.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            uniq_headers.append(name)
    df = pd.DataFrame(rows, columns=uniq_headers)
    return df.loc[:, ~df.columns.duplicated()]


def _parse_bea_results(payload: Any) -> tuple[pd.DataFrame | None, str | None]:
    """
    Parse BEA JSON. Returns (dataframe, error_message).
    BEA nests either Results.Data or Results.Error.
    """
    if not isinstance(payload, dict) or "BEAAPI" not in payload:
        return None, "Missing BEAAPI root"
    bea = payload["BEAAPI"]
    results = bea.get("Results")
    if results is None:
        return None, "Missing BEAAPI.Results"

    # Error object
    if isinstance(results, dict) and "Error" in results:
        err = results["Error"]
        if isinstance(err, dict):
            code = err.get("APIErrorCode", "?")
            desc = err.get("APIErrorDescription", str(err))
            return None, f"BEA API error {code}: {desc}"
        return None, f"BEA API error: {err}"

    # Data may be under Results.Data or Results as a list of tables
    data = None
    if isinstance(results, dict):
        data = results.get("Data")
        if data is None and "Statistic" in results:
            # sometimes metadata-only
            return None, f"BEA Results had no Data (keys={list(results.keys())})"
    elif isinstance(results, list):
        # Rare alternate shape: list of result blocks
        for block in results:
            if isinstance(block, dict) and "Data" in block:
                data = block["Data"]
                break

    if not data:
        return None, f"BEA Results.Data empty (results type={type(results).__name__})"

    df = pd.DataFrame(data)
    if df.empty:
        return None, "BEA Data parsed but empty"
    return df, None


def ingest_bea_trade() -> tuple[pd.DataFrame, dict]:
    """Fetch BEA ITA goods/services aggregates; fall back to synthetic."""
    key = "bea_trade"
    url = DATASETS[key]["url"]

    if not BEA_API_KEY:
        logger.warning("BEA_API_KEY not set — using synthetic BEA series")
    else:
        # Try several ITA indicators / year windows until one returns Data
        attempts = [
            {"Indicator": "ExpGds", "Frequency": "A", "Year": "ALL"},
            {"Indicator": "ImpGds", "Frequency": "A", "Year": "ALL"},
            {"Indicator": "BalGds", "Frequency": "A", "Year": "ALL"},
            {"Indicator": "ExpGds", "Frequency": "A", "Year": "2018,2019,2020,2021,2022,2023,2024,2025"},
            {"Indicator": "BalGds", "Frequency": "A", "Year": "2020,2021,2022,2023,2024"},
            {"Indicator": "ExpGdsServ", "Frequency": "A", "Year": "ALL"},
        ]
        last_err = None
        frames: list[pd.DataFrame] = []
        for extra in attempts:
            params = {
                "UserID": BEA_API_KEY,
                "method": "GetData",
                "DatasetName": "ITA",
                "AreaOrCountry": "AllCountries",
                "ResultFormat": "JSON",
                **extra,
            }
            payload = fetch_json(url, params=params)
            if payload is None:
                last_err = "HTTP/JSON fetch failed"
                continue
            df, err = _parse_bea_results(payload)
            if err:
                last_err = err
                logger.warning("BEA attempt %s failed: %s", extra.get("Indicator"), err)
                # Inactive / invalid key — no point trying more indicators
                if "not active" in err.lower() or "invalid" in err.lower():
                    break
                continue
            assert df is not None
            df["requested_indicator"] = extra.get("Indicator")
            frames.append(df)
            # One successful indicator is enough for a live feed
            break

        if frames:
            out = pd.concat(frames, ignore_index=True)
            # Normalize common BEA ITA fields when present
            rename = {}
            for c in out.columns:
                cl = c.lower()
                if cl in {"timeperiod", "year"}:
                    rename[c] = "year"
                elif cl in {"datavalue", "value"}:
                    rename[c] = "value"
                elif cl == "indicator":
                    rename[c] = "indicator"
                elif cl in {"areaorcountry", "country"}:
                    rename[c] = "area_or_country"
            out = out.rename(columns=rename)
            if "value" in out.columns:
                out["value"] = pd.to_numeric(
                    out["value"].astype(str).str.replace(",", "", regex=False),
                    errors="coerce",
                )
            out.to_csv(DATA_RAW / "bea_ita.csv", index=False)
            return out, _log_entry(
                key,
                "success",
                len(out),
                f"Live BEA ITA columns: {list(out.columns)}",
                "live_api",
            )

        logger.warning("BEA live fetch unavailable (%s) — synthetic fallback", last_err)

    df = synthetic.generate_bea_aggregate()
    df.to_csv(DATA_RAW / "bea_trade_synthetic.csv", index=False)
    note = "Synthetic BEA-style goods & services balances."
    if BEA_API_KEY:
        note += " Key present but API rejected/returned no Data (activate key at apps.bea.gov)."
    else:
        note += " Set BEA_API_KEY for live data."
    return df, _log_entry(key, "fallback_synthetic", len(df), note, "synthetic")


def _census_months(n: int = 12) -> list[str]:
    """Recent published YYYY-MM months (trade stats lag ~1–2 months)."""
    end = (pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.DateOffset(months=2)).to_period("M")
    return [str(end - i) for i in range(n)][::-1]


def _fetch_census_month(flow: str, month: str, hs4: str) -> pd.DataFrame | None:
    """Fetch one month × one HS4 across countries."""
    key_name = "census_imports_hs" if flow == "imports" else "census_exports_hs"
    url = DATASETS[key_name]["url"]
    if flow == "imports":
        get_cols = "CTY_CODE,CTY_NAME,I_COMMODITY,I_COMMODITY_LDESC,GEN_VAL_MO"
        commodity_param = "I_COMMODITY"
    else:
        get_cols = "CTY_CODE,CTY_NAME,E_COMMODITY,E_COMMODITY_LDESC,ALL_VAL_MO"
        commodity_param = "E_COMMODITY"

    params: dict[str, Any] = {
        "get": get_cols,
        "time": month,
        "COMM_LVL": "HS4",
        commodity_param: hs4,
    }
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY

    resp = fetch_response(url, params=params)
    if resp is None:
        return None

    text = resp.text.lstrip()
    if "invalid_key" in resp.url or "<title>Invalid Key</title>" in text or text.lower().startswith("<html"):
        raise RuntimeError(
            "Census API key is invalid or not activated. "
            "Request/activate at https://api.census.gov/data/key_signup.html"
        )

    if not text:
        return None

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.debug("Census non-JSON for %s %s hs=%s: %s", flow, month, hs4, exc)
        return None

    if isinstance(payload, dict) and payload.get("error"):
        logger.debug("Census error for %s %s hs=%s: %s", flow, month, hs4, payload.get("error"))
        return None

    return _census_to_dataframe(payload)


def _normalize_census_live(df: pd.DataFrame, flow: str) -> pd.DataFrame:
    """Map Census columns into agent-friendly schema."""
    out = df.copy()
    out = out.loc[:, ~out.columns.duplicated()]
    if flow == "imports":
        out = out.rename(
            columns={
                "CTY_NAME": "country",
                "I_COMMODITY": "hs_code",
                "I_COMMODITY_LDESC": "commodity",
                "GEN_VAL_MO": "value_usd",
            }
        )
    else:
        out = out.rename(
            columns={
                "CTY_NAME": "country",
                "E_COMMODITY": "hs_code",
                "E_COMMODITY_LDESC": "commodity",
                "ALL_VAL_MO": "value_usd",
            }
        )
    out = out.loc[:, ~out.columns.duplicated()]
    if "time" in out.columns:
        out["date"] = pd.to_datetime(out["time"].astype(str) + "-01", errors="coerce")
    hs = out["hs_code"]
    if isinstance(hs, pd.DataFrame):
        hs = hs.iloc[:, 0]
    out["hs_code"] = hs.astype(str).str.replace(r"\D", "", regex=True).str.zfill(4).str[:4]
    out["value_usd"] = pd.to_numeric(out["value_usd"], errors="coerce").fillna(0.0)
    out["value_usd_m"] = out["value_usd"] / 1_000_000.0
    out["flow"] = flow
    out["commodity"] = out["hs_code"].map(lambda h: _HS_NAME.get(str(h), str(h)))
    out["critical"] = out["hs_code"].map(lambda h: bool(_HS_CRITICAL.get(str(h), False)))
    keep = ["date", "country", "hs_code", "commodity", "critical", "value_usd_m", "flow"]
    return out[[c for c in keep if c in out.columns]].dropna(subset=["date"])


def ingest_census_hs(flow: str = "imports") -> tuple[pd.DataFrame, dict]:
    """Fetch Census HS import/export timeseries; fall back to synthetic."""
    key = "census_imports_hs" if flow == "imports" else "census_exports_hs"

    if not CENSUS_API_KEY:
        logger.warning("CENSUS_API_KEY not set — using synthetic Census %s", flow)
    else:
        months = _census_months(4)
        hs_list = _TARGET_HS4[:8]
        chunks: list[pd.DataFrame] = []
        try:
            for month in months:
                for hs4 in hs_list:
                    part = _fetch_census_month(flow, month, hs4)
                    if part is not None and not part.empty:
                        chunks.append(part)
            if chunks:
                raw = pd.concat(chunks, ignore_index=True)
                df = _normalize_census_live(raw, flow)
                path = DATA_RAW / f"census_{flow}_hs.csv"
                df.to_csv(path, index=False)
                return df, _log_entry(
                    key,
                    "success",
                    len(df),
                    f"Live Census API ({flow}) months={months[0]}..{months[-1]} "
                    f"hs4={len(hs_list)} cols={list(df.columns)}",
                    "live_api",
                )
            logger.warning("Census %s returned no rows for requested window", flow)
        except RuntimeError as exc:
            logger.error("%s", exc)

    trade = synthetic.generate_monthly_trade()
    value_col = "import_value_usd_m" if flow == "imports" else "export_value_usd_m"
    df = trade[["date", "country", "hs_code", "commodity", "critical", value_col]].rename(
        columns={value_col: "value_usd_m"}
    )
    df["flow"] = flow
    path = DATA_RAW / f"census_{flow}_hs_synthetic.csv"
    df.to_csv(path, index=False)
    note = "Synthetic monthly country×commodity values (USD millions)."
    if CENSUS_API_KEY:
        note += " Key present but Census rejected it or returned no data (check activation)."
    else:
        note += " Set CENSUS_API_KEY for live data."
    return df, _log_entry(key, "fallback_synthetic", len(df), note, "synthetic")


def _unified_from_census(imports: pd.DataFrame, exports: pd.DataFrame) -> pd.DataFrame | None:
    """Build unified_trade from live Census import/export frames if possible."""
    if "value_usd_m" not in imports.columns or "flow" not in imports.columns:
        return None
    if imports["flow"].iloc[0] != "imports" and "import" not in str(imports["flow"].iloc[0]):
        # still ok if normalized
        pass

    imp = imports.copy()
    exp = exports.copy() if exports is not None and not exports.empty else pd.DataFrame()

    imp = imp.rename(columns={"value_usd_m": "import_value_usd_m"})
    if not exp.empty and "value_usd_m" in exp.columns:
        exp = exp.rename(columns={"value_usd_m": "export_value_usd_m"})
        merged = pd.merge(
            imp[["date", "country", "hs_code", "commodity", "critical", "import_value_usd_m"]],
            exp[["date", "country", "hs_code", "export_value_usd_m"]],
            on=["date", "country", "hs_code"],
            how="outer",
        )
    else:
        merged = imp[["date", "country", "hs_code", "commodity", "critical", "import_value_usd_m"]].copy()
        merged["export_value_usd_m"] = 0.0

    merged["import_value_usd_m"] = merged["import_value_usd_m"].fillna(0.0)
    merged["export_value_usd_m"] = merged.get("export_value_usd_m", 0.0)
    if "export_value_usd_m" not in merged:
        merged["export_value_usd_m"] = 0.0
    merged["export_value_usd_m"] = merged["export_value_usd_m"].fillna(0.0)
    merged["commodity"] = merged["hs_code"].map(lambda h: _HS_NAME.get(str(h), str(h)))
    merged["critical"] = merged["hs_code"].map(lambda h: _HS_CRITICAL.get(str(h), False))
    merged["date"] = pd.to_datetime(merged["date"])
    merged["year"] = merged["date"].dt.year
    merged["month"] = merged["date"].dt.month
    # Volume proxy from value
    merged["import_volume_teu"] = (merged["import_value_usd_m"] * 1.1).round(1)
    merged["export_volume_teu"] = (merged["export_value_usd_m"] * 1.1).round(1)
    return merged


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

    unified = None
    if imp_log.get("source_mode") == "live_api":
        unified = _unified_from_census(imp_df, exp_df)

    if unified is not None and not unified.empty:
        data["unified_trade"] = unified
        logs.append(
            {
                "dataset_key": "unified_trade",
                "dataset_name": "Unified Trade Table (country × commodity × month)",
                "url": "internal://census_live_merge",
                "source": "Agent Data Engineering Layer",
                "fetched_at_utc": _now_iso(),
                "status": "constructed_from_live_census",
                "source_mode": "live_api",
                "row_count": len(unified),
                "schema_notes": (
                    "Built from live Census imports/exports: date, country, hs_code, "
                    "commodity, critical, import/export value & volume."
                ),
            }
        )
    else:
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
