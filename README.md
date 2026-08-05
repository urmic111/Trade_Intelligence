# Trade Flow Intelligence Agent

Autonomous agentic system that ingests U.S. trade datasets from Data.gov / agency APIs, cleans and normalizes them, detects anomalies, forecasts flows, clusters trade behavior, scores supply-chain risk, and exports a multi-sheet Excel workbook.

## Project structure

```
trade_flow_intelligence/
├── config/settings.py          # Endpoints, paths, analytics params
├── data/{raw,processed,cache}/ # Local data lake
├── outputs/                    # Excel workbooks
├── scripts/run_pipeline.py     # End-to-end runner
└── src/
    ├── ingestion/              # API fetch + synthetic fallbacks
    ├── engineering/            # Clean, normalize, time series
    ├── analytics/              # Anomalies, ARIMA, KMeans, dependency
    ├── risk/                   # Geo / tariff / port composite scores
    ├── insights/               # Narrative + recommendations
    └── reporting/              # Excel exporter (openpyxl)
```

## Quick start

```bash
cd trade_flow_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_pipeline.py
```

Output: `outputs/Trade_Flow_Intelligence_Report.xlsx`

### Excel → CSV → Dashboard

```bash
python scripts/build_dashboard.py
```

This converts each report sheet to `outputs/csv/*.csv`, then builds
`outputs/Trade_Flow_Dashboard.xlsx` (KPI tiles + charts) from those CSVs.

### Optional live APIs

```bash
export CENSUS_API_KEY=your_key   # https://api.census.gov/data/key_signup.html
export BEA_API_KEY=your_key      # https://apps.bea.gov/API/signup/
python scripts/run_pipeline.py
```

Without keys, the agent uses deterministic synthetic series that preserve seasonality, shocks, supplier concentration, and port congestion patterns so analytics remain reproducible.

## Excel sheets

| Sheet | Contents |
|-------|----------|
| Data_Ingestion_Log | Dataset names, URLs, timestamps, row counts, schema notes |
| Cleaned_Data_Summary | Column profiles, missing values, normalization steps |
| Anomalies | Z-score anomalies with severity |
| Forecasts | ARIMA(1,1,1) import/export forecasts for top 20 commodities |
| Clusters | Country & commodity K-means assignments |
| Risk_Scores | Dependency, geo, tariff, disruption, port composite scores |
| Insights_Narrative | Sectioned text insights |
| Recommendations | Actionable guidance by audience |
| Visualizations_Data | Long-form chart data (line / bar / heatmap) |

## Autonomous loop

After each run the agent evaluates source modes (live vs synthetic), logs sheet row counts, identifies missing live datasets, and prints the next-iteration plan.
