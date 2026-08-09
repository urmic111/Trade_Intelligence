# How to open the Trade Flow Tableau dashboard

## Why the old `.twbx` was grayed out

**Tableau Public only opens workbooks that use Hyper extracts** — not live CSV/text connections.
The previous package used live CSV links, so Public grayed it out / refused it.

This rebuild packages `.hyper` extracts inside `Trade_Flow_Dashboard.twbx`.

## Option A — Open the packaged workbook (best)

1. Install [Tableau Public](https://public.tableau.com/app/download) if needed.
2. In **Finder**, go to:
   - `Desktop/Trade_Flow_Tableau/Trade_Flow_Dashboard.twbx`  
     or `Trade_Intelligence/outputs/tableau/Trade_Flow_Dashboard.twbx`
3. Double-click the `.twbx`, **or** in Tableau: **File → Open** → choose that file.
4. If sheets look empty at first, click each worksheet once to refresh marks.

## Option B — Connect to CSV manually (always works)

1. Open Tableau Public → **Connect** → **Text file**
2. Browse to `Desktop/Trade_Flow_Tableau/Data/` (or `outputs/tableau/Data/`)
3. Open `Risk_Scores.csv` first
4. Build:
   - Rows: `commodity_short` · Columns: `SUM(composite_risk_0_100)` · Mark: Bar
5. **Data → New Data Source** → add `Port_Risk.csv`, `Forecasts_Import.csv`, `Anomalies.csv`
6. **Dashboard → New Dashboard** and drag worksheets in

Suggested starter charts:

| Sheet | File | Rows | Columns |
|-------|------|------|---------|
| Risk | Risk_Scores.csv | commodity_short | SUM(composite_risk_0_100) |
| Ports | Port_Risk.csv | port | SUM(port_congestion_score_0_100) |
| Forecast | Forecasts_Import.csv | forecast_date | SUM(forecast_import_usd_m), color=commodity_short |
| Anomalies | Anomalies.csv | commodity_short | SUM(severity_score) |

## Option C — Open a single Hyper extract

In Tableau Public: **Connect → More… → Hyper** → pick any `Data/*.hyper` file
(e.g. `Risk_Scores.hyper`), then build charts as above.

## Rebuild

```bash
python scripts/build_tableau_dashboard.py
```
