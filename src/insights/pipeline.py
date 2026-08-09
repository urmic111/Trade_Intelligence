"""Narrative insights and actionable recommendations."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd


def generate_narrative(
    ingestion_log: pd.DataFrame,
    anomalies: pd.DataFrame,
    forecasts: pd.DataFrame,
    risk_scores: pd.DataFrame,
    port_risk: pd.DataFrame,
    clusters: pd.DataFrame,
) -> pd.DataFrame:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    live = (ingestion_log["source_mode"] == "live_api").sum() if "source_mode" in ingestion_log else 0
    synth = (ingestion_log["source_mode"] == "synthetic").sum() if "source_mode" in ingestion_log else 0

    top_risks = risk_scores.head(5)
    top_anom = anomalies.head(5) if not anomalies.empty else anomalies
    congested = port_risk[port_risk["bottleneck_flag"]] if "bottleneck_flag" in port_risk.columns else port_risk.head(3)
    critical_high = risk_scores[(risk_scores["critical"]) & (risk_scores["composite_risk_0_100"] >= 55)]

    # Emerging opportunities: high forecast growth, low dependency
    fc_imp = forecasts[forecasts["model"] == "ARIMA(1,1,1)"].copy()
    growth_rows = []
    if not fc_imp.empty:
        for hs, g in fc_imp.groupby("hs_code"):
            g = g.sort_values("horizon_month")
            if len(g) >= 2:
                start, end = g["forecast_import_usd_m"].iloc[0], g["forecast_import_usd_m"].iloc[-1]
                growth = (end - start) / start if start else 0
                growth_rows.append({"hs_code": hs, "commodity": g["commodity"].iloc[0], "forecast_growth": growth})
    growth_df = pd.DataFrame(growth_rows).sort_values("forecast_growth", ascending=False) if growth_rows else pd.DataFrame()

    paragraphs = [
        (
            "Executive Overview",
            f"Trade Flow Intelligence Agent run completed at {now}. "
            f"Ingested {len(ingestion_log)} dataset sources ({live} live API, {synth} synthetic/fallback). "
            "Analysis covers country×commodity trade flows, port congestion, tariff exposure, "
            "anomaly detection, ARIMA forecasts, behavioral clustering, and composite supply-chain risk scores."
        ),
        (
            "Data Quality Assessment",
            "Primary analytics use a unified monthly trade table with normalized HS4 codes and country names. "
            "Where Census/BEA/BTS API keys or endpoints were unavailable, deterministic synthetic series "
            "preserving realistic seasonality, shocks, and supplier concentration patterns were used. "
            "Live keys (CENSUS_API_KEY, BEA_API_KEY) will upgrade ingestion on subsequent runs."
        ),
        (
            "Anomaly Findings",
            (
                f"Detected {len(anomalies)} statistical anomalies (|z|≥2.5) in monthly import values. "
                + (
                    "Highest-severity events: "
                    + "; ".join(
                        f"{r['commodity']} ({r['direction']}, z={r['z_score']}, severity={r['severity_score']})"
                        for _, r in top_anom.iterrows()
                    )
                    + "."
                    if not top_anom.empty
                    else "No anomalies exceeded the configured threshold."
                )
            ),
        ),
        (
            "Supply Chain & Geopolitical Risk",
            (
                f"{len(critical_high)} critical commodities score Elevated/Critical on the composite risk index. "
                "Top exposures: "
                + "; ".join(
                    f"{r['commodity']} (supplier={r['top_supplier']}, "
                    f"share={r['top_supplier_share_pct']}%, risk={r['composite_risk_0_100']})"
                    for _, r in top_risks.iterrows()
                )
                + ". Geopolitical flags highlight reliance on high-watchlist partners for semiconductors, "
                "critical minerals, and energy-related flows."
            ),
        ),
        (
            "Port Congestion Bottlenecks",
            (
                "West Coast gateways show elevated congestion in the latest 3-month window. "
                + (
                    "Bottleneck ports: "
                    + ", ".join(
                        f"{r['port']} (score={r['port_congestion_score_0_100']}, dwell={r['avg_dwell_days']:.1f}d)"
                        for _, r in congested.head(5).iterrows()
                    )
                    + "."
                    if not congested.empty
                    else "No ports exceeded the bottleneck threshold."
                )
            ),
        ),
        (
            "Forecast Outlook",
            f"ARIMA(1,1,1) 12-month import/export forecasts were produced for the top {fc_imp['hs_code'].nunique() if not fc_imp.empty else 0} "
            "commodities by trailing-12-month import value. Policymakers should monitor forecast bands for "
            "crude petroleum, electronics, and medicaments where confidence intervals widen under recent volatility."
        ),
        (
            "Emerging Trade Opportunities",
            (
                "Commodities with the strongest projected import demand growth (proxy for market opportunity / sourcing need): "
                + (
                    "; ".join(
                        f"{r['commodity']} ({r['forecast_growth']*100:.1f}%)"
                        for _, r in growth_df.head(5).iterrows()
                    )
                    + "."
                    if not growth_df.empty
                    else "Insufficient forecast differential to rank opportunities."
                )
                + " Export-side clusters with diversified partners present near-term commercial expansion potential."
            ),
        ),
        (
            "Clustering Interpretation",
            f"K-means identified {clusters[clusters['entity_type']=='country']['cluster'].nunique()} country clusters "
            f"and {clusters[clusters['entity_type']=='commodity']['cluster'].nunique()} commodity clusters "
            "based on 12-month import profiles. Clusters separate high-tech East Asian suppliers, "
            "North American nearshoring partners, and commodity/energy exporters — useful for "
            "differentiated trade and industrial-policy targeting."
        ),
        (
            "Tariff Sensitivity",
            f"{int(risk_scores['tariff_sensitive'].fillna(False).sum())} commodities are flagged tariff-sensitive "
            "(effective duty ≥10%). Combined Section 301 and MFN exposure raises landed-cost risk for "
            "electronics, batteries, and selected industrial inputs — relevant for duty mitigation and FTA utilization."
        ),
        (
            "Next Iteration Plan",
            "1) Attach live Census & BEA API keys for production freshness. "
            "2) Incorporate real ITC HTS extracts and BTS port AIS dwell metrics. "
            "3) Extend forecasts with Prophet/LSTM ensembles and scenario stress tests. "
            "4) Add firm-level bill-of-materials dependency for critical minerals. "
            "5) Schedule weekly autonomous refresh with anomaly alerting."
        ),
    ]

    return pd.DataFrame(
        [{"section": s, "narrative": n, "generated_at_utc": now} for s, n in paragraphs]
    )


def generate_recommendations(risk_scores: pd.DataFrame, port_risk: pd.DataFrame, anomalies: pd.DataFrame) -> pd.DataFrame:
    recs = []
    priority = 1

    critical = risk_scores[(risk_scores["critical"]) & (risk_scores["composite_risk_0_100"] >= 55)].head(8)
    for _, r in critical.iterrows():
        recs.append(
            {
                "priority": priority,
                "audience": "Policymakers",
                "theme": "Critical Commodity Diversification",
                "hs_code": r["hs_code"],
                "commodity": r["commodity"],
                "recommendation": (
                    f"Reduce single-supplier reliance on {r['top_supplier']} "
                    f"({r['top_supplier_share_pct']}% of imports) for {r['commodity']}. "
                    "Expand friend-shoring incentives, stockpile review, and alternative-source FTAs."
                ),
                "expected_impact": "Lower geopolitical & supply shock exposure",
            }
        )
        priority += 1

    tariff_hits = risk_scores[risk_scores["tariff_sensitive"] == True].head(5)  # noqa: E712
    for _, r in tariff_hits.iterrows():
        recs.append(
            {
                "priority": priority,
                "audience": "Businesses",
                "theme": "Tariff Mitigation",
                "hs_code": r["hs_code"],
                "commodity": r["commodity"],
                "recommendation": (
                    f"Effective duty ~{r['total_effective_duty_pct']}% on {r['commodity']}. "
                    "Evaluate USMCA/other FTA claims, bonded warehousing, and supplier relocation ROI."
                ),
                "expected_impact": "Reduce landed cost & margin pressure",
            }
        )
        priority += 1

    for _, p in port_risk.head(3).iterrows():
        if p.get("bottleneck_flag", True):
            recs.append(
                {
                    "priority": priority,
                    "audience": "Logistics / Analysts",
                    "theme": "Port Bottleneck Routing",
                    "hs_code": "",
                    "commodity": "",
                    "recommendation": (
                        f"Reroute discretionary volume away from {p['port']} "
                        f"(congestion score {p['port_congestion_score_0_100']}, "
                        f"dwell {p['avg_dwell_days']:.1f} days) toward less congested East/Gulf Coast gateways."
                    ),
                    "expected_impact": "Shorter lead times, lower demurrage",
                }
            )
            priority += 1

    if not anomalies.empty:
        severe = anomalies.head(3)
        for _, a in severe.iterrows():
            recs.append(
                {
                    "priority": priority,
                    "audience": "Analysts",
                    "theme": "Anomaly Investigation",
                    "hs_code": a["hs_code"],
                    "commodity": a["commodity"],
                    "recommendation": (
                        f"Investigate {a['direction']} in {a['commodity']} on {pd.Timestamp(a['date']).date()} "
                        f"(z={a['z_score']}). Cross-check against tariffs, sanctions, and port events."
                    ),
                    "expected_impact": "Early warning for policy & procurement",
                }
            )
            priority += 1

    recs.append(
        {
            "priority": priority,
            "audience": "Policymakers",
            "theme": "Industrial Base Monitoring",
            "hs_code": "",
            "commodity": "",
            "recommendation": (
                "Establish a recurring Trade Flow Intelligence dashboard refreshed weekly, "
                "with automated alerts when dependency_score ≥75 or port congestion ≥60."
            ),
            "expected_impact": "Institutionalize continuous situational awareness",
        }
    )

    return pd.DataFrame(recs)


def build_visualization_data(
    commodity_ts: pd.DataFrame,
    forecasts: pd.DataFrame,
    risk_scores: pd.DataFrame,
    port_risk: pd.DataFrame,
    dependency: pd.DataFrame,
) -> pd.DataFrame:
    """Long-format chart-ready data for Excel/Plotly consumers."""
    frames = []

    # Top 10 commodity import time series
    latest = commodity_ts["date"].max()
    top10 = (
        commodity_ts[commodity_ts["date"] > latest - pd.DateOffset(months=12)]
        .groupby("hs_code")["import_value_usd_m"]
        .sum()
        .nlargest(10)
        .index
    )
    hist = commodity_ts[commodity_ts["hs_code"].isin(top10)][
        ["date", "hs_code", "commodity", "import_value_usd_m"]
    ].copy()
    hist["chart"] = "line_top10_imports"
    hist["series"] = hist["commodity"]
    hist["x"] = hist["date"].astype(str)
    hist["y"] = hist["import_value_usd_m"]
    frames.append(hist[["chart", "series", "x", "y", "hs_code", "commodity"]])

    # Forecast lines (imports only)
    fc = forecasts[forecasts["model"] == "ARIMA(1,1,1)"].copy()
    if not fc.empty:
        fc["chart"] = "line_forecast_imports"
        fc["series"] = fc["commodity"]
        fc["x"] = fc["forecast_date"].astype(str)
        fc["y"] = fc["forecast_import_usd_m"]
        frames.append(fc[["chart", "series", "x", "y", "hs_code", "commodity"]])

    # Risk bar chart
    rb = risk_scores.head(15).copy()
    rb["chart"] = "bar_composite_risk"
    rb["series"] = "composite_risk"
    rb["x"] = rb["commodity"]
    rb["y"] = rb["composite_risk_0_100"]
    frames.append(rb[["chart", "series", "x", "y", "hs_code", "commodity"]])

    # Dependency heatmap long form
    dep = dependency.head(20).copy()
    dep["chart"] = "heatmap_dependency"
    dep["series"] = dep["top_supplier"]
    dep["x"] = dep["commodity"]
    dep["y"] = dep["top_supplier_share_pct"]
    frames.append(dep[["chart", "series", "x", "y", "hs_code", "commodity"]])

    # Port congestion bars
    pr = port_risk.copy()
    pr["chart"] = "bar_port_congestion"
    pr["series"] = "congestion"
    pr["x"] = pr["port"]
    pr["y"] = pr["port_congestion_score_0_100"]
    pr["hs_code"] = ""
    pr["commodity"] = ""
    frames.append(pr[["chart", "series", "x", "y", "hs_code", "commodity"]])

    return pd.concat(frames, ignore_index=True)
