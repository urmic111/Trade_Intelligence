"""Cleaning, normalization, and time-series construction."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from config.settings import DATA_PROCESSED

logger = logging.getLogger(__name__)

# ISO-ish country name normalization map
COUNTRY_ALIASES = {
    "korea, south": "South Korea",
    "korea, republic of": "South Korea",
    "viet nam": "Vietnam",
    "russian federation": "Russia",
    "united states": "United States",
    "u.s.": "United States",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "taiwan, province of china": "Taiwan",
}

# Census geographic aggregates / trade blocs — not real supplier countries
AGGREGATE_PARTNERS = frozenset(
    {
        "TOTAL FOR ALL COUNTRIES",
        "AFRICA",
        "ASIA",
        "EUROPE",
        "NORTH AMERICA",
        "SOUTH AMERICA",
        "CENTRAL AMERICA",
        "AUSTRALIA AND OCEANIA",
        "EURO AREA",
        "EUROPEAN UNION",
        "APEC",
        "ASEAN",
        "CACM",
        "CAFTA-DR",
        "LAFTA",
        "NATO",
        "OECD",
        "PACIFIC RIM COUNTRIES",
        "TWENTY LATIN AMERICAN REPUBLICS",
        "USMCA (NAFTA)",
        "WORLD",
    }
)


def normalize_country(name: str) -> str:
    if not isinstance(name, str):
        return str(name)
    key = name.strip().lower()
    return COUNTRY_ALIASES.get(key, name.strip().title() if name.islower() else name.strip())


def is_aggregate_partner(name: str) -> bool:
    """True for Census region/bloc totals that must not enter supplier concentration."""
    if not isinstance(name, str):
        return True
    key = name.strip().upper()
    if key in AGGREGATE_PARTNERS:
        return True
    if key.startswith("TOTAL ") or key.endswith(" TOTAL"):
        return True
    return False


def normalize_hs(code: Any) -> str:
    s = str(code).strip().replace(".", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return s
    return digits.zfill(4)[:4]


def clean_unified_trade(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Clean missing values, normalize codes, return cleaned DF + profile summary."""
    original_rows = len(df)
    out = df.copy()
    out["country"] = out["country"].map(normalize_country)
    out["hs_code"] = out["hs_code"].map(normalize_hs)
    out["date"] = pd.to_datetime(out["date"])

    numeric_cols = [
        c
        for c in out.columns
        if c.endswith("_usd_m") or c.endswith("_teu") or c in ("import_value_usd_m", "export_value_usd_m")
    ]
    missing_before = {c: int(out[c].isna().sum()) for c in numeric_cols if c in out.columns}

    for c in numeric_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            median = out[c].median()
            out[c] = out[c].fillna(median if pd.notna(median) else 0.0)
            out.loc[out[c] < 0, c] = 0.0

    out = out.drop_duplicates(subset=["date", "country", "hs_code"], keep="last")
    before_agg = len(out)
    out = out[~out["country"].map(is_aggregate_partner)].copy()
    aggregates_removed = before_agg - len(out)
    out = out.sort_values(["date", "hs_code", "country"]).reset_index(drop=True)

    profile = {
        "table": "unified_trade",
        "original_rows": original_rows,
        "cleaned_rows": len(out),
        "rows_removed": original_rows - len(out),
        "aggregates_removed": aggregates_removed,
        "missing_before": missing_before,
        "missing_after": {c: int(out[c].isna().sum()) for c in numeric_cols if c in out.columns},
        "normalization_steps": [
            "country alias normalization",
            "HS codes zero-padded to 4 digits",
            "dates coerced to datetime",
            "numeric nulls filled with column median",
            "negative values clipped to 0",
            "deduplicated on date×country×hs_code",
            "removed Census aggregate partners (regions/blocs/totals)",
        ],
        "columns": list(out.columns),
        "dtypes": {c: str(t) for c, t in out.dtypes.items()},
    }
    out.to_csv(DATA_PROCESSED / "unified_trade.csv", index=False)
    return out, profile


def clean_ports(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    for c in ("teu_throughput", "congestion_index", "avg_dwell_days", "vessel_queue"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(out[c].median())
    out["congestion_index"] = out["congestion_index"].clip(0, 1)
    profile = {
        "table": "ports",
        "original_rows": len(df),
        "cleaned_rows": len(out),
        "rows_removed": 0,
        "missing_before": {},
        "missing_after": {},
        "normalization_steps": [
            "dates coerced",
            "numeric fillna median",
            "congestion_index clipped to [0,1]",
        ],
        "columns": list(out.columns),
        "dtypes": {c: str(t) for c, t in out.dtypes.items()},
    }
    return out, profile


def build_time_series(trade: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly import/export totals by commodity for forecasting."""
    ts = (
        trade.groupby(["date", "hs_code", "commodity"], as_index=False)
        .agg(
            import_value_usd_m=("import_value_usd_m", "sum"),
            export_value_usd_m=("export_value_usd_m", "sum"),
            import_volume_teu=("import_volume_teu", "sum"),
            export_volume_teu=("export_volume_teu", "sum"),
        )
        .sort_values(["hs_code", "date"])
    )
    ts.to_csv(DATA_PROCESSED / "commodity_timeseries.csv", index=False)
    return ts


def build_country_commodity_matrix(trade: pd.DataFrame) -> pd.DataFrame:
    """Latest-12-month import totals by country × commodity."""
    latest = trade["date"].max()
    window = trade[trade["date"] > latest - pd.DateOffset(months=12)]
    window = window[~window["country"].map(is_aggregate_partner)]
    mat = (
        window.groupby(["country", "hs_code", "commodity"], as_index=False)["import_value_usd_m"]
        .sum()
        .rename(columns={"import_value_usd_m": "import_12m_usd_m"})
    )
    return mat


def profile_to_rows(profiles: list[dict]) -> pd.DataFrame:
    """Flatten cleaning profiles into a summary table for Excel."""
    rows = []
    for p in profiles:
        rows.append(
            {
                "table": p["table"],
                "original_rows": p["original_rows"],
                "cleaned_rows": p["cleaned_rows"],
                "rows_removed": p["rows_removed"],
                "n_columns": len(p["columns"]),
                "columns": ", ".join(p["columns"]),
                "normalization_steps": " | ".join(p["normalization_steps"]),
                "missing_value_notes": str(p.get("missing_before", {})),
            }
        )
    return pd.DataFrame(rows)


def run_engineering(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Clean all datasets and build analytics-ready tables."""
    profiles: list[dict] = []
    cleaned: dict[str, pd.DataFrame] = {}

    trade, trade_profile = clean_unified_trade(raw["unified_trade"])
    cleaned["unified_trade"] = trade
    profiles.append(trade_profile)

    ports, ports_profile = clean_ports(raw["ports"])
    cleaned["ports"] = ports
    profiles.append(ports_profile)

    cleaned["tariffs"] = raw["tariffs"].copy()
    profiles.append(
        {
            "table": "tariffs",
            "original_rows": len(raw["tariffs"]),
            "cleaned_rows": len(raw["tariffs"]),
            "rows_removed": 0,
            "missing_before": {},
            "missing_after": {},
            "normalization_steps": ["passthrough — already structured"],
            "columns": list(raw["tariffs"].columns),
            "dtypes": {c: str(t) for c, t in raw["tariffs"].dtypes.items()},
        }
    )

    cleaned["supply_chain"] = raw["supply_chain"].copy()
    cleaned["supply_chain"]["event_date"] = pd.to_datetime(cleaned["supply_chain"]["event_date"])
    profiles.append(
        {
            "table": "supply_chain",
            "original_rows": len(raw["supply_chain"]),
            "cleaned_rows": len(cleaned["supply_chain"]),
            "rows_removed": 0,
            "missing_before": {},
            "missing_after": {},
            "normalization_steps": ["event_date datetime coercion"],
            "columns": list(cleaned["supply_chain"].columns),
            "dtypes": {c: str(t) for c, t in cleaned["supply_chain"].dtypes.items()},
        }
    )

    cleaned["bea"] = raw["bea"].copy()
    if "date" in cleaned["bea"].columns:
        cleaned["bea"]["date"] = pd.to_datetime(cleaned["bea"]["date"])
    profiles.append(
        {
            "table": "bea",
            "original_rows": len(raw["bea"]),
            "cleaned_rows": len(cleaned["bea"]),
            "rows_removed": 0,
            "missing_before": {},
            "missing_after": {},
            "normalization_steps": ["date coercion if present"],
            "columns": list(cleaned["bea"].columns),
            "dtypes": {c: str(t) for c, t in cleaned["bea"].dtypes.items()},
        }
    )

    cleaned["commodity_ts"] = build_time_series(trade)
    cleaned["country_commodity"] = build_country_commodity_matrix(trade)

    summary = profile_to_rows(profiles)
    logger.info("Engineering complete: %s cleaned tables", len(cleaned))
    return cleaned, summary
