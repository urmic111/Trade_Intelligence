# Trade Flow Intelligence  
### Product Detail Document

| | |
|---|---|
| **Product** | Trade Flow Intelligence Agent |
| **Version** | 1.0 |
| **Audience** | Policymakers, trade analysts, supply-chain & business strategy teams |
| **Status** | Production-ready pipeline (synthetic fallback when live APIs unavailable) |
| **Live demo** | https://urmic111.github.io/Trade_Intelligence/ |

---

## 1. Product overview

**Trade Flow Intelligence** is an autonomous analytics product that turns fragmented U.S. public trade data into decision-ready risk, forecast, and opportunity insights.

Users get a single operating picture of import/export dynamics: which commodities are dependency-concentrated, which ports are congested, where anomalies appear, and what actions to consider next—without manually stitching Census, BEA, BTS, tariff, and commodity feeds.

The product runs as a modular Python pipeline and delivers results as **Excel workbooks**, **CSV datasets**, and an **interactive HTML dashboard** (also published to GitHub Pages).

---

## 2. Problem

Trade stakeholders face three recurring gaps:

1. **Fragmented sources** — Goods/services balances, HS-level country flows, port stats, tariffs, and disruption signals live in different systems and formats.  
2. **Slow interpretation** — Analysts spend hours cleaning codes (HS, country names) before they can ask policy questions.  
3. **Opaque risk** — Single-supplier reliance, tariff exposure, and congestion rarely appear in one scored, explainable view.

Trade Flow Intelligence closes those gaps with an end-to-end ingest → engineer → model → report workflow.

---

## 3. Who it’s for

| Persona | Primary need | Product answer |
|---------|--------------|----------------|
| **Policy analyst** | Early warning on critical commodities | Risk tiers, dependency scores, narrative brief |
| **Trade economist** | Forecast context for top flows | ARIMA import/export outlooks + anomaly flags |
| **Supply-chain lead** | Bottlenecks & routing pressure | Port congestion scores, dwell, recommendations |
| **Business strategist** | Tariff & sourcing exposure | Duty-sensitive flags, supplier concentration |

---

## 4. Core capabilities

### Data acquisition
- Connects to Data.gov / agency endpoints (BEA, Census HS trade, BTS ports, Commerce disruption proxies, ITC tariff schedules, USDA/Census commodity flows).  
- Validates freshness and schema; logs source mode (**live API** vs **synthetic fallback**).  
- Retries failed HTTP calls with exponential backoff.

### Data engineering
- Cleans missing values; normalizes country names and HS codes.  
- Builds unified trade tables and monthly time series for modeling.

### Analytics & modeling
- **Anomalies** — Z-score spikes/drops in commodity import flows.  
- **Forecasts** — ARIMA(1,1,1) horizons for top commodities.  
- **Clusters** — K-means groupings of countries and commodities by trade behavior.  
- **Dependency** — Top-supplier share, concentration, and reliance scores.

### Risk & insights
- Composite risk from dependency, geopolitics, tariffs, disruptions, and port congestion.  
- Narrative sections and prioritized recommendations by audience (policy, business, logistics).

### Distribution
- Multi-sheet Excel report + Excel dashboard.  
- CSV export pack for BI tools.  
- HTML dashboard (Plotly) for browser viewing and GitHub Pages publishing.

---

## 5. Key outputs

| Deliverable | Description |
|-------------|-------------|
| `Trade_Flow_Intelligence_Report.xlsx` | Full analytic workbook (ingestion log, cleaned summary, anomalies, forecasts, clusters, risk, insights, recommendations, viz data) |
| `Trade_Flow_Dashboard.xlsx` | Executive Excel dashboard with KPI tiles and charts |
| `outputs/csv/*.csv` | Sheet-level CSV sources for Tableau/Power BI/custom tools |
| `Trade_Flow_Dashboard.html` | Interactive web dashboard |
| GitHub Pages site | Hosted HTML dashboard for sharing |

**Representative KPIs surfaced in the UI:** critical/elevated risk counts, anomaly count, average dependency, max port congestion score, recommendation count.

---

## 6. How it works (user journey)

1. **Run pipeline** — `python scripts/run_pipeline.py`  
2. **Refresh CSVs & Excel dashboard** — `python scripts/build_dashboard.py`  
3. **Refresh HTML / Pages source** — `python scripts/build_html_dashboard.py`  
4. **Consume** — Open Excel, browse HTML locally, or visit the published Pages URL.  
5. **Optional live data** — Set `CENSUS_API_KEY` / `BEA_API_KEY` and re-run for production freshness.

No specialized BI license is required for the HTML path; Excel is optional for offline briefing packs.

---

## 7. Product principles

- **Resilience over fragility** — API failure does not halt insight generation; fallbacks are logged transparently.  
- **Explainability** — Scores ship with drivers (supplier, duty, congestion, events), not black-box ranks alone.  
- **Reproducibility** — Seeded synthetics, staged raw/processed folders, and rebuild scripts keep results auditable.  
- **Audience fit** — Recommendations are tagged for policymakers, businesses, analysts, and logistics users.

---

## 8. Scope & boundaries (v1.0)

**In scope:** U.S.-centric public trade analytics; monthly commodity/country views; port congestion indicators; tariff sensitivity flags; dashboarding and export.

**Out of scope (current):** Firm-level BOM dependency, real-time vessel AIS, paid commercial data vendors, mobile native apps, multi-tenant SaaS auth.

**Known dependency:** Without agency API keys, analytics use deterministic synthetic series that preserve realistic seasonality, shocks, and concentration patterns for demos and pipeline testing.

---

## 9. Success metrics

| Metric | Target signal |
|--------|----------------|
| Time-to-insight | Full refresh to dashboard in one scripted run |
| Coverage | Top commodities + major partners + major ports in one pack |
| Actionability | Ranked recommendations with expected impact |
| Shareability | HTML Pages URL usable without local setup |
| Trust | Ingestion log shows live vs fallback for every source |

---

## 10. Roadmap (next iterations)

1. Wire live ITC HTS extracts and verified BTS port dwell feeds.  
2. Ensemble forecasts (Prophet/LSTM) with scenario stress tests.  
3. Alerting when dependency ≥ 75 or port congestion ≥ 60.  
4. Scheduled weekly refresh (cron/Actions) with changelog.  
5. Optional authenticated SaaS wrapper for institutional users.

---

## 11. Summary

Trade Flow Intelligence is a **trade-risk and flow intelligence product** that automates the path from public data to executive-ready insight. It helps rising decision cycles move from scattered tables to a scored, narrated, shareable dashboard—built for analysts who need speed without sacrificing transparency.

**Primary CTA:** Run the pipeline → open the HTML dashboard → share the Pages link for stakeholder review.
