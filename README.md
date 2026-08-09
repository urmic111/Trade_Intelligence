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

### CSV → HTML dashboard (recommended)

```bash
python scripts/build_html_dashboard.py
```

Writes:
- `outputs/dashboard/Trade_Flow_Dashboard.html`
- `docs/index.html` (GitHub Pages source)

### GitHub Pages

The live dashboard is published from the `docs/` folder:

**https://urmic111.github.io/Trade_Intelligence/**

After refreshing data, rebuild HTML and push `docs/index.html` to update the site.

### CSV → Tableau dashboard

```bash
python scripts/build_tableau_dashboard.py
```

Builds `outputs/tableau/Trade_Flow_Dashboard.twbx` with Hyper extracts.
See `outputs/tableau/HOW_TO_OPEN.md` if Tableau Public grays out the file.

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
