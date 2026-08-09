"""Anomaly detection, forecasting, clustering, and dependency scoring."""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.arima.model import ARIMA

from config.settings import (
    ANOMALY_ZSCORE_THRESHOLD,
    FORECAST_HORIZON_MONTHS,
    RANDOM_SEED,
    TOP_N_COMMODITIES,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


def detect_anomalies(commodity_ts: pd.DataFrame, z_thresh: float = ANOMALY_ZSCORE_THRESHOLD) -> pd.DataFrame:
    """Detect import-value anomalies with methods that work on short live series.

    Uses leave-one-out z-scores (so a spike does not inflate its own baseline) and
    month-over-month % moves. Adaptive threshold for short histories.
    """
    records = []
    ts = commodity_ts.copy()
    ts["date"] = pd.to_datetime(ts["date"])

    for hs, grp in ts.groupby("hs_code"):
        g = grp.sort_values("date").reset_index(drop=True)
        vals = g["import_value_usd_m"].astype(float).values
        n = len(vals)
        if n < 3:
            continue
        commodity = str(g["commodity"].iloc[0])
        # Short Census pulls need a slightly softer gate than long synthetic histories
        thresh = min(z_thresh, 2.0) if n < 12 else z_thresh
        mom_thresh = 0.12 if n < 12 else 0.18

        for i, (date, value) in enumerate(zip(g["date"], vals)):
            others = np.delete(vals, i)
            mu = float(others.mean())
            sigma = float(others.std(ddof=1)) if len(others) > 1 else 0.0
            holdout_z = float((value - mu) / sigma) if sigma > 1e-9 else 0.0
            mom = float(value / vals[i - 1] - 1.0) if i > 0 and vals[i - 1] > 0 else 0.0

            z_hit = abs(holdout_z) >= thresh
            mom_hit = i > 0 and abs(mom) >= mom_thresh
            if not (z_hit or mom_hit):
                continue

            # Prefer the stronger signal for direction/severity
            if abs(holdout_z) >= abs(mom) * 5:  # z dominates when large
                direction = "spike" if holdout_z > 0 else "drop"
                severity = min(10.0, abs(holdout_z) * 1.5)
                driver = f"holdout |z|={abs(holdout_z):.2f}"
            else:
                direction = "spike" if mom > 0 else "drop"
                severity = min(10.0, abs(mom) * 25)
                driver = f"MoM {mom:+.1%}"
            if z_hit and mom_hit:
                severity = min(10.0, max(severity, abs(holdout_z) * 1.5, abs(mom) * 25))
                driver = f"holdout |z|={abs(holdout_z):.2f}; MoM {mom:+.1%}"

            records.append(
                {
                    "date": date,
                    "hs_code": hs,
                    "commodity": commodity,
                    "metric": "import_value_usd_m",
                    "value": round(float(value), 2),
                    "z_score": round(holdout_z, 3),
                    "direction": direction,
                    "severity_score": round(float(severity), 2),
                    "baseline_mean": round(mu, 2),
                    "notes": f"{driver}; n={n}; gate |z|≥{thresh} or |MoM|≥{mom_thresh:.0%}",
                }
            )

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "hs_code",
                "commodity",
                "metric",
                "value",
                "z_score",
                "direction",
                "severity_score",
                "baseline_mean",
                "notes",
            ]
        )

    # One row per commodity: keep the most severe recent event for the dashboard
    df = df.sort_values(["commodity", "severity_score", "date"], ascending=[True, False, False])
    top = df.groupby("commodity", as_index=False).head(1)
    return top.sort_values("severity_score", ascending=False).reset_index(drop=True)


def _fit_arima_forecast(series: pd.Series, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit ARIMA(1,1,1) with fallback to naive drift."""
    y = series.astype(float).values
    try:
        model = ARIMA(y, order=(1, 1, 1))
        fitted = model.fit()
        fc = fitted.get_forecast(steps=horizon)
        mean = fc.predicted_mean
        ci = fc.conf_int(alpha=0.2)
        lower = ci.iloc[:, 0].values if hasattr(ci, "iloc") else ci[:, 0]
        upper = ci.iloc[:, 1].values if hasattr(ci, "iloc") else ci[:, 1]
        return np.asarray(mean), np.asarray(lower), np.asarray(upper)
    except Exception:
        last = y[-1]
        drift = (y[-1] - y[0]) / max(len(y) - 1, 1)
        mean = np.array([last + drift * (i + 1) for i in range(horizon)])
        lower = mean * 0.9
        upper = mean * 1.1
        return mean, lower, upper


def forecast_top_commodities(
    commodity_ts: pd.DataFrame,
    top_n: int = TOP_N_COMMODITIES,
    horizon: int = FORECAST_HORIZON_MONTHS,
) -> pd.DataFrame:
    """ARIMA forecasts for top N commodities by latest-12m import value."""
    latest = commodity_ts["date"].max()
    window = commodity_ts[commodity_ts["date"] > latest - pd.DateOffset(months=12)]
    ranking = (
        window.groupby(["hs_code", "commodity"], as_index=False)["import_value_usd_m"]
        .sum()
        .sort_values("import_value_usd_m", ascending=False)
        .head(top_n)
    )

    rows = []
    for _, row in ranking.iterrows():
        hs, commodity = row["hs_code"], row["commodity"]
        series = (
            commodity_ts[commodity_ts["hs_code"] == hs]
            .sort_values("date")
            .set_index("date")["import_value_usd_m"]
        )
        mean, lower, upper = _fit_arima_forecast(series, horizon)
        last_date = series.index.max()
        future_dates = pd.date_range(
            start=last_date + pd.offsets.MonthBegin(1), periods=horizon, freq="MS"
        )
        for i, dt in enumerate(future_dates):
            rows.append(
                {
                    "hs_code": hs,
                    "commodity": commodity,
                    "forecast_date": dt,
                    "horizon_month": i + 1,
                    "forecast_import_usd_m": round(float(max(0, mean[i])), 2),
                    "lower_80": round(float(max(0, lower[i])), 2),
                    "upper_80": round(float(max(0, upper[i])), 2),
                    "model": "ARIMA(1,1,1)",
                    "historical_12m_import_usd_m": round(float(row["import_value_usd_m"]), 2),
                }
            )

        # Also forecast exports
        series_x = (
            commodity_ts[commodity_ts["hs_code"] == hs]
            .sort_values("date")
            .set_index("date")["export_value_usd_m"]
        )
        mean_x, lower_x, upper_x = _fit_arima_forecast(series_x, horizon)
        for i, dt in enumerate(future_dates):
            rows.append(
                {
                    "hs_code": hs,
                    "commodity": commodity,
                    "forecast_date": dt,
                    "horizon_month": i + 1,
                    "forecast_import_usd_m": round(float(max(0, mean_x[i])), 2),
                    "lower_80": round(float(max(0, lower_x[i])), 2),
                    "upper_80": round(float(max(0, upper_x[i])), 2),
                    "model": "ARIMA(1,1,1)-exports",
                    "historical_12m_import_usd_m": round(float(row["import_value_usd_m"]), 2),
                }
            )

    return pd.DataFrame(rows)


def _title_country(name: str) -> str:
    s = str(name).strip()
    if not s:
        return s
    # Preserve short acronyms; otherwise prefer readable title case
    if s.isupper() and len(s) > 3:
        return s.title()
    return s


def cluster_countries(country_commodity: pd.DataFrame, n_clusters: int = 5) -> pd.DataFrame:
    """K-means cluster major supplier countries by commodity import profile."""
    from src.engineering.pipeline import is_aggregate_partner

    cc = country_commodity[~country_commodity["country"].map(is_aggregate_partner)].copy()
    if cc.empty:
        return pd.DataFrame(
            columns=[
                "entity_type",
                "entity_id",
                "entity_name",
                "cluster",
                "total_import_12m_usd_m",
                "cluster_label",
            ]
        )

    totals = cc.groupby("country", as_index=True)["import_12m_usd_m"].sum().sort_values(ascending=False)
    # Keep the volume-driving partners so clusters are interpretable (not 200 near-zero rows)
    min_share = 0.0025  # 0.25% of total imports
    keep = totals[totals >= totals.sum() * min_share]
    if len(keep) < max(n_clusters * 2, 8):
        keep = totals.head(min(40, len(totals)))
    else:
        keep = keep.head(40)
    cc = cc[cc["country"].isin(keep.index)]

    pivot = cc.pivot_table(
        index="country",
        columns="hs_code",
        values="import_12m_usd_m",
        fill_value=0.0,
    )
    # Volume + composition: log total helps separate mega-suppliers from mid-tier
    volume = np.log1p(pivot.sum(axis=1).values).reshape(-1, 1)
    composition = pivot.div(pivot.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0).values
    features = np.hstack([volume, composition])
    scaler = StandardScaler()
    X = scaler.fit_transform(features)
    k = min(n_clusters, max(1, len(pivot)))
    labels = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10).fit_predict(X)

    country_df = pd.DataFrame(
        {
            "entity_type": "country",
            "entity_id": pivot.index.astype(str),
            "entity_name": [_title_country(c) for c in pivot.index],
            "cluster": labels,
            "total_import_12m_usd_m": pivot.sum(axis=1).values.round(2),
        }
    )

    # Readable labels: rank clusters by volume, name after the largest member
    cluster_rank = (
        country_df.groupby("cluster")["total_import_12m_usd_m"]
        .sum()
        .sort_values(ascending=False)
    )
    label_map: dict[int, str] = {}
    for rank, cluster_id in enumerate(cluster_rank.index, start=1):
        members = country_df[country_df["cluster"] == cluster_id].sort_values(
            "total_import_12m_usd_m", ascending=False
        )
        lead = members.iloc[0]["entity_name"]
        n = len(members)
        if n == 1:
            label_map[int(cluster_id)] = f"C{rank}: {lead}"
        else:
            label_map[int(cluster_id)] = f"C{rank}: {lead}-led ({n})"
    country_df["cluster_label"] = country_df["cluster"].map(label_map)

    # Commodity clusters (same HS set, countries as features)
    pivot_c = cc.pivot_table(
        index="hs_code",
        columns="country",
        values="import_12m_usd_m",
        fill_value=0.0,
    )
    name_map = cc.drop_duplicates("hs_code").set_index("hs_code")["commodity"].to_dict()
    Xc = StandardScaler().fit_transform(pivot_c.values)
    kc = min(n_clusters, max(1, len(pivot_c)))
    labels_c = KMeans(n_clusters=kc, random_state=RANDOM_SEED, n_init=10).fit_predict(Xc)

    commodity_df = pd.DataFrame(
        {
            "entity_type": "commodity",
            "entity_id": pivot_c.index.astype(str),
            "entity_name": [name_map.get(h, h) for h in pivot_c.index],
            "cluster": labels_c,
            "total_import_12m_usd_m": pivot_c.sum(axis=1).values.round(2),
        }
    )
    for cluster_id in commodity_df["cluster"].unique():
        mask = commodity_df["cluster"] == cluster_id
        top = commodity_df.loc[mask].sort_values("total_import_12m_usd_m", ascending=False).iloc[0]
        commodity_df.loc[mask, "cluster_label"] = f"Commodity: {top['entity_name']}"

    return (
        pd.concat([country_df, commodity_df], ignore_index=True)
        .sort_values(["entity_type", "total_import_12m_usd_m"], ascending=[True, False])
        .reset_index(drop=True)
    )


def compute_dependency_scores(trade: pd.DataFrame) -> pd.DataFrame:
    """Supplier concentration / HHI / single-source reliance by commodity."""
    from src.engineering.pipeline import is_aggregate_partner

    latest = trade["date"].max()
    window = trade[trade["date"] > latest - pd.DateOffset(months=12)].copy()
    window = window[~window["country"].map(is_aggregate_partner)]
    rows = []
    for (hs, commodity), grp in window.groupby(["hs_code", "commodity"]):
        by_country = grp.groupby("country")["import_value_usd_m"].sum().sort_values(ascending=False)
        total = by_country.sum()
        if total <= 0 or by_country.empty:
            continue
        shares = by_country / total
        hhi = float((shares ** 2).sum())
        top1_country = str(shares.index[0])
        top1_share = float(shares.iloc[0])
        top3_share = float(shares.iloc[:3].sum())
        critical = bool(grp["critical"].iloc[0]) if "critical" in grp.columns else False
        # top1_share and hhi are on [0,1]; weighted blend is already on [0,100]
        base = top1_share * 60 + hhi * 40
        dependency_score = round(min(100.0, base * (1.2 if critical else 1.0)), 1)
        rows.append(
            {
                "hs_code": hs,
                "commodity": commodity,
                "critical": critical,
                "top_supplier": top1_country,
                "top_supplier_share_pct": round(top1_share * 100, 2),
                "top3_share_pct": round(top3_share * 100, 2),
                "hhi": round(hhi, 4),
                "n_suppliers": int((shares > 0.01).sum()),
                "import_12m_usd_m": round(float(total), 2),
                "dependency_score_0_100": dependency_score,
                "risk_tier": (
                    "Critical" if dependency_score >= 75 else
                    "Elevated" if dependency_score >= 50 else
                    "Moderate" if dependency_score >= 30 else
                    "Low"
                ),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "hs_code",
                "commodity",
                "critical",
                "top_supplier",
                "top_supplier_share_pct",
                "top3_share_pct",
                "hhi",
                "n_suppliers",
                "import_12m_usd_m",
                "dependency_score_0_100",
                "risk_tier",
            ]
        )
    return pd.DataFrame(rows).sort_values("dependency_score_0_100", ascending=False).reset_index(drop=True)


def run_analytics(cleaned: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    logger.info("Running anomaly detection…")
    anomalies = detect_anomalies(cleaned["commodity_ts"])
    logger.info("Running ARIMA forecasts…")
    forecasts = forecast_top_commodities(cleaned["commodity_ts"])
    logger.info("Clustering countries/commodities…")
    clusters = cluster_countries(cleaned["country_commodity"])
    logger.info("Computing dependency scores…")
    dependency = compute_dependency_scores(cleaned["unified_trade"])
    return {
        "anomalies": anomalies,
        "forecasts": forecasts,
        "clusters": clusters,
        "dependency": dependency,
    }
