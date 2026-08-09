"""Supply-chain risk, geopolitical flags, and tariff sensitivity."""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

GEOPOLITICAL_WATCHLIST = {
    "China": 0.85,
    "Russia": 0.90,
    "Taiwan": 0.70,
    "Saudi Arabia": 0.55,
    "Vietnam": 0.40,
    "Mexico": 0.25,
    "Canada": 0.15,
}


def compute_port_risk(ports: pd.DataFrame) -> pd.DataFrame:
    latest = ports["date"].max()
    recent = ports[ports["date"] > latest - pd.DateOffset(months=3)]
    agg = (
        recent.groupby("port", as_index=False)
        .agg(
            avg_congestion=("congestion_index", "mean"),
            avg_dwell_days=("avg_dwell_days", "mean"),
            avg_vessel_queue=("vessel_queue", "mean"),
            teu_throughput=("teu_throughput", "mean"),
        )
    )
    agg["port_congestion_score_0_100"] = (
        agg["avg_congestion"] * 50
        + (agg["avg_dwell_days"] / 15).clip(0, 1) * 30
        + (agg["avg_vessel_queue"] / 40).clip(0, 1) * 20
    ).round(1)
    agg["bottleneck_flag"] = agg["port_congestion_score_0_100"] >= 60
    return agg.sort_values("port_congestion_score_0_100", ascending=False)


def compute_risk_scores(
    dependency: pd.DataFrame,
    tariffs: pd.DataFrame,
    ports: pd.DataFrame,
    supply_chain: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    port_risk = compute_port_risk(ports)
    max_port = float(port_risk["port_congestion_score_0_100"].max())

    # Recent disruption intensity by commodity
    sc = supply_chain.copy()
    cutoff = sc["event_date"].max() - pd.DateOffset(months=12)
    recent_sc = sc[sc["event_date"] >= cutoff]
    sc_by_hs = (
        recent_sc.groupby("hs_code", as_index=False)
        .agg(avg_event_severity=("severity_1_10", "mean"), n_events=("event_id", "count"))
    )

    merged = dependency.copy()
    tariffs_n = tariffs.copy()
    sc_n = sc_by_hs.copy()
    for frame in (merged, tariffs_n, sc_n):
        frame["hs_code"] = frame["hs_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    merged = merged.merge(
        tariffs_n[["hs_code", "total_effective_duty_pct", "tariff_sensitive"]],
        on="hs_code",
        how="left",
    )
    merged = merged.merge(sc_n, on="hs_code", how="left")
    merged["avg_event_severity"] = merged["avg_event_severity"].fillna(0)
    merged["n_events"] = merged["n_events"].fillna(0).astype(int)
    # Live Census partners are often ALL CAPS; map watchlist case-insensitively
    geo_lookup = {k.lower(): v for k, v in GEOPOLITICAL_WATCHLIST.items()}
    merged["geo_risk_factor"] = (
        merged["top_supplier"].astype(str).str.strip().str.lower().map(geo_lookup).fillna(0.3)
    )

    merged["port_congestion_indicator"] = round(max_port, 1)
    merged["tariff_risk_0_100"] = (merged["total_effective_duty_pct"].fillna(0) / 50 * 100).clip(0, 100).round(1)
    merged["disruption_risk_0_100"] = (
        (merged["avg_event_severity"] / 10 * 60) + (merged["n_events"].clip(0, 10) / 10 * 40)
    ).round(1)

    merged["composite_risk_0_100"] = (
        merged["dependency_score_0_100"] * 0.40
        + merged["geo_risk_factor"] * 100 * 0.25
        + merged["tariff_risk_0_100"] * 0.15
        + merged["disruption_risk_0_100"] * 0.10
        + merged["port_congestion_indicator"] * 0.10
    ).round(1)

    merged["geopolitical_flag"] = merged["geo_risk_factor"] >= 0.7
    merged["risk_tier"] = merged["composite_risk_0_100"].apply(
        lambda x: "Critical" if x >= 75 else "Elevated" if x >= 55 else "Moderate" if x >= 35 else "Low"
    )

    cols = [
        "hs_code", "commodity", "critical", "top_supplier", "top_supplier_share_pct",
        "dependency_score_0_100", "geo_risk_factor", "geopolitical_flag",
        "total_effective_duty_pct", "tariff_sensitive", "tariff_risk_0_100",
        "avg_event_severity", "n_events", "disruption_risk_0_100",
        "port_congestion_indicator", "composite_risk_0_100", "risk_tier",
    ]
    result = merged[cols].sort_values("composite_risk_0_100", ascending=False).reset_index(drop=True)
    return result, port_risk


def run_risk(cleaned: dict[str, pd.DataFrame], analytics: dict[str, pd.DataFrame]):
    risk_scores, port_risk = compute_risk_scores(
        analytics["dependency"],
        cleaned["tariffs"],
        cleaned["ports"],
        cleaned["supply_chain"],
    )
    logger.info("Risk scoring complete: %s commodities", len(risk_scores))
    return {"risk_scores": risk_scores, "port_risk": port_risk}
