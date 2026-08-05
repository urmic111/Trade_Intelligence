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
    """Z-score anomalies on monthly import values per commodity."""
    records = []
    for hs, grp in commodity_ts.groupby("hs_code"):
        g = grp.sort_values("date")
        vals = g["import_value_usd_m"].astype(float)
        mu, sigma = vals.mean(), vals.std(ddof=1)
        if sigma == 0 or np.isnan(sigma):
            continue
        z = (vals - mu) / sigma
        commodity = g["commodity"].iloc[0]
        for idx, (date, value, zscore) in enumerate(zip(g["date"], vals, z)):
            if abs(zscore) >= z_thresh:
                direction = "spike" if zscore > 0 else "drop"
                severity = min(10.0, abs(zscore) * 2)
                records.append(
                    {
                        "date": date,
                        "hs_code": hs,
                        "commodity": commodity,
                        "metric": "import_value_usd_m",
                        "value": round(float(value), 2),
                        "z_score": round(float(zscore), 3),
                        "direction": direction,
                        "severity_score": round(severity, 2),
                        "baseline_mean": round(float(mu), 2),
                        "notes": f"Month {idx + 1} of series; |z|≥{z_thresh}",
                    }
                )

    # Partner concentration anomalies: single-country share jumps
    # (handled separately via dependency module flags in risk layer)

    df = pd.DataFrame(records)
    if df.empty:
        return df
    return df.sort_values("severity_score", ascending=False).reset_index(drop=True)


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


def cluster_countries(country_commodity: pd.DataFrame, n_clusters: int = 5) -> pd.DataFrame:
    """K-means cluster countries by commodity import profile."""
    pivot = country_commodity.pivot_table(
        index="country",
        columns="hs_code",
        values="import_12m_usd_m",
        fill_value=0.0,
    )
    scaler = StandardScaler()
    X = scaler.fit_transform(pivot.values)
    k = min(n_clusters, len(pivot))
    km = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10)
    labels = km.fit_predict(X)

    # Commodity clusters
    pivot_c = country_commodity.pivot_table(
        index="hs_code",
        columns="country",
        values="import_12m_usd_m",
        fill_value=0.0,
    )
    # attach commodity names
    name_map = (
        country_commodity.drop_duplicates("hs_code").set_index("hs_code")["commodity"].to_dict()
    )
    Xc = StandardScaler().fit_transform(pivot_c.values)
    kc = min(n_clusters, len(pivot_c))
    labels_c = KMeans(n_clusters=kc, random_state=RANDOM_SEED, n_init=10).fit_predict(Xc)

    country_df = pd.DataFrame(
        {
            "entity_type": "country",
            "entity_id": pivot.index,
            "entity_name": pivot.index,
            "cluster": labels,
            "total_import_12m_usd_m": pivot.sum(axis=1).values.round(2),
        }
    )
    # Cluster centroids summary
    for i, c in enumerate(country_df["cluster"].unique()):
        mask = country_df["cluster"] == c
        country_df.loc[mask, "cluster_label"] = f"CountryCluster-{c}"

    commodity_df = pd.DataFrame(
        {
            "entity_type": "commodity",
            "entity_id": pivot_c.index,
            "entity_name": [name_map.get(h, h) for h in pivot_c.index],
            "cluster": labels_c,
            "total_import_12m_usd_m": pivot_c.sum(axis=1).values.round(2),
        }
    )
    for i, c in enumerate(commodity_df["cluster"].unique()):
        mask = commodity_df["cluster"] == c
        commodity_df.loc[mask, "cluster_label"] = f"CommodityCluster-{c}"

    return pd.concat([country_df, commodity_df], ignore_index=True)


def compute_dependency_scores(trade: pd.DataFrame) -> pd.DataFrame:
    """Supplier concentration / HHI / single-source reliance by commodity."""
    latest = trade["date"].max()
    window = trade[trade["date"] > latest - pd.DateOffset(months=12)]
    rows = []
    for (hs, commodity), grp in window.groupby(["hs_code", "commodity"]):
        by_country = grp.groupby("country")["import_value_usd_m"].sum().sort_values(ascending=False)
        total = by_country.sum()
        if total <= 0:
            continue
        shares = by_country / total
        hhi = float((shares ** 2).sum())
        top1_country = shares.index[0]
        top1_share = float(shares.iloc[0])
        top3_share = float(shares.iloc[:3].sum())
        critical = bool(grp["critical"].iloc[0]) if "critical" in grp.columns else False
        dependency_score = round(min(100.0, (top1_share * 60 + hhi * 40) * (1.2 if critical else 1.0) * 100 / 1.2), 1)
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
