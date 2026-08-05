"""Synthetic / realistic trade data generators used when live APIs are unavailable."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config.settings import COMMODITIES, COUNTRIES, PORTS, RANDOM_SEED


def _rng(seed: int = RANDOM_SEED) -> np.random.Generator:
    return np.random.default_rng(seed)


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def generate_monthly_trade(n_months: int = 60, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Generate monthly import/export values by country × commodity (USD millions)."""
    rng = _rng(seed)
    end = _month_start()
    dates = pd.date_range(end=end, periods=n_months, freq="MS")
    rows: list[dict] = []

    # Country/commodity affinity weights (higher = more trade)
    country_w = {c: rng.uniform(0.3, 2.5) for c in COUNTRIES}
    # Concentrate critical minerals on a few suppliers
    critical_suppliers = {
        "2844": ["Canada", "Australia", "China"],
        "8112": ["China", "Russia", "Brazil"],
        "2615": ["Brazil", "Australia", "Canada"],
        "2804": ["China", "Germany", "Japan"],
        "8542": ["Taiwan", "South Korea", "China", "Malaysia"],
        "8507": ["China", "South Korea", "Japan"],
    }

    for i, dt in enumerate(dates):
        seasonal = 1.0 + 0.08 * np.sin(2 * np.pi * dt.month / 12)
        trend = 1.0 + 0.004 * i
        shock = 1.0
        # Inject anomalies: 2020-style drop, late spike
        if i in (18, 19):
            shock = 0.72
        if i == n_months - 3:
            shock = 1.35

        for commodity in COMMODITIES:
            hs = commodity["hs"]
            base = rng.uniform(80, 1200)
            for country in COUNTRIES:
                affinity = country_w[country]
                if hs in critical_suppliers:
                    affinity *= 3.5 if country in critical_suppliers[hs] else 0.15

                import_val = max(0.1, base * affinity * seasonal * trend * shock * rng.uniform(0.85, 1.15))
                export_val = max(0.1, import_val * rng.uniform(0.4, 1.3))
                # Dependency spike: China semiconductors mid-series drop
                if hs == "8542" and country == "China" and i >= n_months - 8:
                    import_val *= 0.55

                rows.append(
                    {
                        "date": dt,
                        "year": dt.year,
                        "month": dt.month,
                        "country": country,
                        "hs_code": hs,
                        "commodity": commodity["name"],
                        "critical": commodity["critical"],
                        "import_value_usd_m": round(import_val, 2),
                        "export_value_usd_m": round(export_val, 2),
                        "import_volume_teu": round(import_val * rng.uniform(0.8, 1.4), 1),
                        "export_volume_teu": round(export_val * rng.uniform(0.8, 1.4), 1),
                    }
                )
    return pd.DataFrame(rows)


def generate_port_stats(n_months: int = 36, seed: int = RANDOM_SEED + 1) -> pd.DataFrame:
    """Generate port-level throughput and congestion indicators."""
    rng = _rng(seed)
    end = _month_start()
    dates = pd.date_range(end=end, periods=n_months, freq="MS")
    rows: list[dict] = []
    for i, dt in enumerate(dates):
        for port in PORTS:
            base_teu = rng.uniform(200_000, 900_000)
            congestion = rng.uniform(0.15, 0.55)
            if port in ("Los Angeles", "Long Beach") and i >= n_months - 6:
                congestion = min(0.95, congestion + 0.25)
            dwell = 3.0 + congestion * 8 + rng.uniform(-0.5, 0.5)
            rows.append(
                {
                    "date": dt,
                    "port": port,
                    "teu_throughput": round(base_teu * (1 + 0.002 * i), 0),
                    "congestion_index": round(congestion, 3),
                    "avg_dwell_days": round(dwell, 2),
                    "vessel_queue": int(congestion * rng.integers(5, 40)),
                }
            )
    return pd.DataFrame(rows)


def generate_tariff_schedule(seed: int = RANDOM_SEED + 2) -> pd.DataFrame:
    """Generate HTS tariff / duty schedule snapshot."""
    rng = _rng(seed)
    rows = []
    for commodity in COMMODITIES:
        mfn = round(rng.uniform(0, 25), 2)
        section301 = round(rng.choice([0, 7.5, 25]), 1) if commodity["critical"] else 0.0
        rows.append(
            {
                "hs_code": commodity["hs"],
                "commodity": commodity["name"],
                "mfn_duty_pct": mfn,
                "section_301_addl_pct": section301,
                "total_effective_duty_pct": round(mfn + section301, 2),
                "tariff_sensitive": (mfn + section301) >= 10,
                "critical": commodity["critical"],
            }
        )
    return pd.DataFrame(rows)


def generate_supply_chain_events(seed: int = RANDOM_SEED + 3) -> pd.DataFrame:
    """Generate supply-chain disruption event log."""
    rng = _rng(seed)
    event_types = [
        "Port Congestion",
        "Geopolitical Embargo",
        "Natural Disaster",
        "Labor Strike",
        "Cyber Incident",
        "Factory Shutdown",
    ]
    rows = []
    for i in range(40):
        commodity = COMMODITIES[int(rng.integers(0, len(COMMODITIES)))]
        country = COUNTRIES[int(rng.integers(0, len(COUNTRIES)))]
        severity = round(float(rng.uniform(1, 10)), 1)
        rows.append(
            {
                "event_id": f"SCD-{1000 + i}",
                "event_date": pd.Timestamp("2023-01-01") + pd.Timedelta(days=int(rng.integers(0, 900))),
                "event_type": rng.choice(event_types),
                "country": country,
                "hs_code": commodity["hs"],
                "commodity": commodity["name"],
                "severity_1_10": severity,
                "estimated_delay_days": int(severity * rng.uniform(1, 5)),
                "source": "Commerce / Synthetic Fallback",
            }
        )
    return pd.DataFrame(rows).sort_values("event_date").reset_index(drop=True)


def generate_bea_aggregate(n_months: int = 60, seed: int = RANDOM_SEED + 4) -> pd.DataFrame:
    """Generate BEA-style aggregate goods & services trade balance series."""
    rng = _rng(seed)
    end = _month_start()
    dates = pd.date_range(end=end, periods=n_months, freq="MS")
    rows = []
    goods_exp, goods_imp = 140_000.0, 210_000.0
    svc_exp, svc_imp = 70_000.0, 55_000.0
    for i, dt in enumerate(dates):
        goods_exp *= 1 + rng.uniform(-0.01, 0.015)
        goods_imp *= 1 + rng.uniform(-0.01, 0.018)
        svc_exp *= 1 + rng.uniform(-0.005, 0.012)
        svc_imp *= 1 + rng.uniform(-0.005, 0.01)
        rows.append(
            {
                "date": dt,
                "goods_exports_usd_m": round(goods_exp, 1),
                "goods_imports_usd_m": round(goods_imp, 1),
                "services_exports_usd_m": round(svc_exp, 1),
                "services_imports_usd_m": round(svc_imp, 1),
                "goods_balance_usd_m": round(goods_exp - goods_imp, 1),
                "services_balance_usd_m": round(svc_exp - svc_imp, 1),
                "overall_balance_usd_m": round(
                    (goods_exp - goods_imp) + (svc_exp - svc_imp), 1
                ),
            }
        )
    return pd.DataFrame(rows)
