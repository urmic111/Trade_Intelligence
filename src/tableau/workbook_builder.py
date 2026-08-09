"""
Build a Tableau Public–compatible packaged workbook (.twbx).

Tableau Public grays out / rejects workbooks with live CSV (textscan)
connections. This builder creates .hyper extracts and packages them.
"""

from __future__ import annotations

import logging
import shutil
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import pantab

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = ROOT / "outputs" / "csv"
TABLEAU_DIR = ROOT / "outputs" / "tableau"
DATA_DIR = TABLEAU_DIR / "Data"
TWB_PATH = TABLEAU_DIR / "Trade_Flow_Dashboard.twb"
TWBX_PATH = TABLEAU_DIR / "Trade_Flow_Dashboard.twbx"
DESKTOP_PACK = Path.home() / "Desktop" / "Trade_Flow_Tableau"


def _uid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def prepare_frames(csv_dir: Path = CSV_DIR) -> dict[str, pd.DataFrame]:
    """Load pipeline CSVs and return cleaned Tableau frames."""

    def load(name: str) -> pd.DataFrame:
        path = csv_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Missing source CSV: {path}")
        return pd.read_csv(path)

    risk = load("Risk_Scores.csv")
    risk["hs_code"] = risk["hs_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    for col in (
        "top_supplier_share_pct",
        "dependency_score_0_100",
        "geo_risk_factor",
        "total_effective_duty_pct",
        "tariff_risk_0_100",
        "avg_event_severity",
        "disruption_risk_0_100",
        "port_congestion_indicator",
        "composite_risk_0_100",
    ):
        if col in risk.columns:
            risk[col] = pd.to_numeric(risk[col], errors="coerce")
    for col in ("critical", "geopolitical_flag", "tariff_sensitive"):
        risk[col] = risk[col].astype(str).str.lower().isin(["true", "1", "yes"])
    risk["commodity_short"] = risk["commodity"].astype(str).str.slice(0, 32)

    ports = load("Port_Risk.csv")
    for col in (
        "avg_congestion",
        "avg_dwell_days",
        "avg_vessel_queue",
        "teu_throughput",
        "port_congestion_score_0_100",
    ):
        ports[col] = pd.to_numeric(ports[col], errors="coerce")
    ports["bottleneck_flag"] = ports["bottleneck_flag"].astype(str).str.lower().isin(["true", "1", "yes"])

    fc = load("Forecasts.csv")
    fc = fc[fc["model"].astype(str).str.fullmatch(r"ARIMA\(1,1,1\)", na=False)].copy()
    fc["hs_code"] = fc["hs_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    fc["forecast_date"] = pd.to_datetime(fc["forecast_date"], errors="coerce")
    for col in ("horizon_month", "forecast_import_usd_m", "lower_80", "upper_80", "historical_12m_import_usd_m"):
        fc[col] = pd.to_numeric(fc[col], errors="coerce")
    fc["commodity_short"] = fc["commodity"].astype(str).str.slice(0, 32)
    top_hs = (
        fc.groupby("hs_code")["historical_12m_import_usd_m"].first().nlargest(8).index
        if len(fc)
        else []
    )
    fc = fc[fc["hs_code"].isin(top_hs)].copy()

    anom = load("Anomalies.csv")
    anom["date"] = pd.to_datetime(anom["date"], errors="coerce")
    anom["hs_code"] = anom["hs_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    for col in ("value", "z_score", "severity_score", "baseline_mean"):
        anom[col] = pd.to_numeric(anom[col], errors="coerce")
    anom["commodity_short"] = anom["commodity"].astype(str).str.slice(0, 32)

    clusters = load("Clusters.csv")
    clusters["total_import_12m_usd_m"] = pd.to_numeric(clusters["total_import_12m_usd_m"], errors="coerce")
    clusters["cluster"] = pd.to_numeric(clusters["cluster"], errors="coerce").astype("Int64")

    dep = load("Dependency_Detail.csv")
    dep["hs_code"] = dep["hs_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    for col in (
        "top_supplier_share_pct",
        "top3_share_pct",
        "hhi",
        "n_suppliers",
        "import_12m_usd_m",
        "dependency_score_0_100",
    ):
        dep[col] = pd.to_numeric(dep[col], errors="coerce")
    dep["commodity_short"] = dep["commodity"].astype(str).str.slice(0, 32)

    recs = load("Recommendations.csv")
    recs["priority"] = pd.to_numeric(recs["priority"], errors="coerce")
    if "hs_code" in recs.columns:
        recs["hs_code"] = recs["hs_code"].astype(str).str.replace(r"\.0$", "", regex=True)

    kpi = pd.DataFrame(
        [
            {
                "kpi_critical_risks": int((risk["risk_tier"] == "Critical").sum()),
                "kpi_elevated_risks": int((risk["risk_tier"] == "Elevated").sum()),
                "kpi_anomalies": len(anom),
                "kpi_avg_dependency": round(float(risk["dependency_score_0_100"].mean()), 1),
                "kpi_max_port_score": round(float(ports["port_congestion_score_0_100"].max()), 1),
                "kpi_commodities_forecasted": int(fc["hs_code"].nunique()) if len(fc) else 0,
                "kpi_recommendations": len(recs),
                "kpi_bottleneck_ports": int(ports["bottleneck_flag"].sum()),
            }
        ]
    )

    facts = []
    for _, r in risk.iterrows():
        facts.append(
            {
                "domain": "risk",
                "entity": r["commodity_short"],
                "category": r["risk_tier"],
                "metric": "composite_risk",
                "value": float(r["composite_risk_0_100"]),
                "detail": str(r["top_supplier"]),
            }
        )
    for _, r in ports.iterrows():
        facts.append(
            {
                "domain": "port",
                "entity": r["port"],
                "category": "bottleneck" if r["bottleneck_flag"] else "normal",
                "metric": "congestion_score",
                "value": float(r["port_congestion_score_0_100"]),
                "detail": f"dwell={float(r['avg_dwell_days']):.1f}d",
            }
        )
    for _, r in anom.iterrows():
        facts.append(
            {
                "domain": "anomaly",
                "entity": r["commodity_short"],
                "category": r["direction"],
                "metric": "severity",
                "value": float(r["severity_score"]),
                "detail": str(r["date"].date()) if pd.notna(r["date"]) else "",
            }
        )
    for _, r in dep.iterrows():
        facts.append(
            {
                "domain": "dependency",
                "entity": r["commodity_short"],
                "category": r["risk_tier"],
                "metric": "top_supplier_share_pct",
                "value": float(r["top_supplier_share_pct"]),
                "detail": str(r["top_supplier"]),
            }
        )

    return {
        "Risk_Scores": risk,
        "Port_Risk": ports,
        "Forecasts_Import": fc,
        "Anomalies": anom,
        "Clusters": clusters,
        "Dependency_Detail": dep,
        "Recommendations": recs,
        "KPI_Summary": kpi,
        "Dashboard_Facts": pd.DataFrame(facts),
    }


def write_extracts(frames: dict[str, pd.DataFrame], data_dir: Path = DATA_DIR) -> dict[str, Path]:
    """Write CSV copies + Hyper extracts (Tableau Public requires extracts)."""
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for name, df in frames.items():
        csv_path = data_dir / f"{name}.csv"
        df.to_csv(csv_path, index=False)

        hyper_path = data_dir / f"{name}.hyper"
        # pantab uses schema public / table <name>
        pantab.frame_to_hyper(df, hyper_path, table=name)
        paths[name] = hyper_path
        logger.info("Extract %s: %s rows → %s", name, len(df), hyper_path.name)
    return paths


def _column_xml(df: pd.DataFrame) -> str:
    lines = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            datatype, role, type_ = "date", "dimension", "ordinal"
        elif pd.api.types.is_bool_dtype(s):
            datatype, role, type_ = "boolean", "dimension", "nominal"
        elif pd.api.types.is_integer_dtype(s):
            if c.startswith("kpi_"):
                datatype, role, type_ = "integer", "measure", "quantitative"
            elif c.lower() in {"hs_code", "cluster", "horizon_month", "priority", "n_suppliers", "n_events"}:
                datatype, role, type_ = "integer", "dimension", "ordinal"
            else:
                datatype, role, type_ = "integer", "measure", "quantitative"
        elif pd.api.types.is_float_dtype(s) or pd.api.types.is_numeric_dtype(s):
            datatype, role, type_ = "real", "measure", "quantitative"
        else:
            datatype, role, type_ = "string", "dimension", "nominal"
        caption = c.replace("_", " ").title()
        lines.append(
            f'      <column caption="{_escape(caption)}" datatype="{datatype}" name="[{_escape(c)}]" role="{role}" type="{type_}" />'
        )
    return "\n".join(lines)


def _hyper_datasource(caption: str, ds_name: str, table: str, filename: str, df: pd.DataFrame) -> str:
    cols = _column_xml(df)
    return f"""  <datasource caption="{_escape(caption)}" inline="true" name="{_escape(ds_name)}" version="18.1">
    <connection class="hyper" dbname="Data/{_escape(filename)}" password="" schema="public" sslmode="" username="">
      <relation name="{_escape(table)}" table="[public].[{_escape(table)}]" type="table" />
    </connection>
{cols}
    <layout dim-ordering="alphabetic" measure-ordering="alphabetic" />
  </datasource>"""


def _worksheet_bar(name: str, ds: str, dim: str, measure: str, title: str) -> str:
    return f"""  <worksheet name="{_escape(name)}">
    <table>
      <view>
        <datasources>
          <datasource caption="{_escape(ds)}" name="{_escape(ds)}" />
        </datasources>
        <datasource-dependencies datasource="{_escape(ds)}">
          <column datatype="string" name="[{_escape(dim)}]" role="dimension" type="nominal" />
          <column datatype="real" name="[{_escape(measure)}]" role="measure" type="quantitative" />
          <column-instance column="[{_escape(dim)}]" derivation="None" name="[{_escape(dim)}]" pivot="key" type="nominal" />
          <column-instance column="[{_escape(measure)}]" derivation="Sum" name="[sum:{_escape(measure)}:qk]" pivot="key" type="quantitative" />
        </datasource-dependencies>
        <aggregation value="true" />
      </view>
      <style>
        <style-rule element="worksheet">
          <format attr="title" value="{_escape(title)}" />
        </style-rule>
      </style>
      <panes>
        <pane selection-relaxation-option="selection-relaxation-allow">
          <view><breakdown value="auto" /></view>
          <mark class="Bar" />
        </pane>
      </panes>
      <rows>[{_escape(ds)}].[{_escape(dim)}]</rows>
      <cols>[{_escape(ds)}].[sum:{_escape(measure)}:qk]</cols>
    </table>
    <simple-id uuid="{_uid()}" />
  </worksheet>"""


def _worksheet_line(name: str, ds: str, date_f: str, measure: str, series: str, title: str) -> str:
    return f"""  <worksheet name="{_escape(name)}">
    <table>
      <view>
        <datasources>
          <datasource caption="{_escape(ds)}" name="{_escape(ds)}" />
        </datasources>
        <datasource-dependencies datasource="{_escape(ds)}">
          <column datatype="date" name="[{_escape(date_f)}]" role="dimension" type="ordinal" />
          <column datatype="string" name="[{_escape(series)}]" role="dimension" type="nominal" />
          <column datatype="real" name="[{_escape(measure)}]" role="measure" type="quantitative" />
          <column-instance column="[{_escape(date_f)}]" derivation="None" name="[{_escape(date_f)}]" pivot="key" type="ordinal" />
          <column-instance column="[{_escape(series)}]" derivation="None" name="[{_escape(series)}]" pivot="key" type="nominal" />
          <column-instance column="[{_escape(measure)}]" derivation="Sum" name="[sum:{_escape(measure)}:qk]" pivot="key" type="quantitative" />
        </datasource-dependencies>
        <aggregation value="true" />
      </view>
      <style>
        <style-rule element="worksheet">
          <format attr="title" value="{_escape(title)}" />
        </style-rule>
      </style>
      <panes>
        <pane selection-relaxation-option="selection-relaxation-allow">
          <view><breakdown value="auto" /></view>
          <mark class="Line" />
          <encodings>
            <color column="[{_escape(ds)}].[{_escape(series)}]" />
          </encodings>
        </pane>
      </panes>
      <rows>[{_escape(ds)}].[sum:{_escape(measure)}:qk]</rows>
      <cols>[{_escape(ds)}].[{_escape(date_f)}]</cols>
    </table>
    <simple-id uuid="{_uid()}" />
  </worksheet>"""


def _dashboard(name: str, sheets: list[str]) -> str:
    zones = [
        f"""      <zone h="70000" id="1" type-v2="text" w="100000" x="0" y="0">
        <formatted-text>
          <run bold="true" fontcolor="#0B1F3A" fontsize="18">Trade Flow Intelligence — Executive Dashboard</run>
          <run fontcolor="#4A5568" fontsize="11">  ·  Hyper extract sourced (Tableau Public compatible)</run>
        </formatted-text>
      </zone>"""
    ]
    layout = [
        (sheets[0], "0", "70000", "50000", "430000"),
        (sheets[1], "50000", "70000", "50000", "430000"),
        (sheets[2], "0", "500000", "50000", "500000"),
        (sheets[3], "50000", "500000", "50000", "500000"),
    ]
    for i, (ws, x, y, w, h) in enumerate(layout, start=2):
        zones.append(
            f'      <zone h="{h}" id="{i}" name="{_escape(ws)}" type-v2="worksheet" w="{w}" x="{x}" y="{y}" />'
        )
    return f"""  <dashboard name="{_escape(name)}">
    <size maxheight="1200" maxwidth="1600" minheight="900" minwidth="1200" sizing-mode="fixed" />
    <zones>
{chr(10).join(zones)}
    </zones>
    <simple-id uuid="{_uid()}" />
  </dashboard>"""


def build_twb(frames: dict[str, pd.DataFrame], twb_path: Path = TWB_PATH) -> Path:
    specs = [
        ("Risk Scores", "ds.risk", "Risk_Scores", "Risk_Scores.hyper"),
        ("Port Risk", "ds.ports", "Port_Risk", "Port_Risk.hyper"),
        ("Import Forecasts", "ds.forecasts", "Forecasts_Import", "Forecasts_Import.hyper"),
        ("Anomalies", "ds.anomalies", "Anomalies", "Anomalies.hyper"),
        ("Clusters", "ds.clusters", "Clusters", "Clusters.hyper"),
        ("Dependency Detail", "ds.dependency", "Dependency_Detail", "Dependency_Detail.hyper"),
        ("Recommendations", "ds.recs", "Recommendations", "Recommendations.hyper"),
        ("KPI Summary", "ds.kpi", "KPI_Summary", "KPI_Summary.hyper"),
        ("Dashboard Facts", "ds.facts", "Dashboard_Facts", "Dashboard_Facts.hyper"),
    ]
    ds_xml = [
        _hyper_datasource(cap, ds, table, fn, frames[table])
        for cap, ds, table, fn in specs
        if table in frames
    ]

    worksheets = [
        _worksheet_bar("Composite Risk", "ds.risk", "commodity_short", "composite_risk_0_100", "Composite Supply-Chain Risk"),
        _worksheet_bar("Port Congestion", "ds.ports", "port", "port_congestion_score_0_100", "Port Congestion Scores"),
        _worksheet_line("Import Forecasts", "ds.forecasts", "forecast_date", "forecast_import_usd_m", "commodity_short", "12-Month Import Forecast (USD m)"),
        _worksheet_bar("Anomaly Severity", "ds.anomalies", "commodity_short", "severity_score", "Anomaly Severity"),
        _worksheet_bar("Supplier Share", "ds.dependency", "commodity_short", "top_supplier_share_pct", "Top Supplier Share %"),
        _worksheet_bar("Fact Metrics", "ds.facts", "entity", "value", "Unified Dashboard Facts"),
    ]
    names = [
        "Composite Risk",
        "Port Congestion",
        "Import Forecasts",
        "Anomaly Severity",
        "Supplier Share",
        "Fact Metrics",
        "Executive Dashboard",
    ]
    windows = "\n".join(
        f'    <window class="{"dashboard" if n == "Executive Dashboard" else "worksheet"}" name="{_escape(n)}" />'
        for n in names
    )

    xml = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook original-version='18.1' source-build='2024.1.0' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences />
  <datasources>
{chr(10).join(ds_xml)}
  </datasources>
  <worksheets>
{chr(10).join(worksheets)}
  </worksheets>
  <dashboards>
{_dashboard("Executive Dashboard", ["Composite Risk", "Port Congestion", "Import Forecasts", "Anomaly Severity"])}
  </dashboards>
  <windows source-height='30'>
{windows}
  </windows>
</workbook>
"""
    twb_path.parent.mkdir(parents=True, exist_ok=True)
    twb_path.write_text(xml, encoding="utf-8")
    logger.info("Wrote workbook: %s", twb_path)
    return twb_path


def package_twbx(twb_path: Path = TWB_PATH, data_dir: Path = DATA_DIR, twbx_path: Path = TWBX_PATH) -> Path:
    twbx_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(twbx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(twb_path, arcname=twb_path.name)
        for hyper in sorted(data_dir.glob("*.hyper")):
            zf.write(hyper, arcname=f"Data/{hyper.name}")
    logger.info("Wrote packaged workbook: %s (%s bytes)", twbx_path, twbx_path.stat().st_size)
    return twbx_path


def write_howto(tableau_dir: Path = TABLEAU_DIR) -> Path:
    path = tableau_dir / "HOW_TO_OPEN.md"
    path.write_text(
        """# How to open the Trade Flow Tableau dashboard

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
""",
        encoding="utf-8",
    )
    return path


def sync_desktop_pack(tableau_dir: Path = TABLEAU_DIR, desktop: Path = DESKTOP_PACK) -> Path:
    """Copy openable pack to Desktop for Tableau Public file picker."""
    if desktop.exists():
        shutil.rmtree(desktop)
    desktop.mkdir(parents=True)
    shutil.copy2(tableau_dir / "Trade_Flow_Dashboard.twbx", desktop / "Trade_Flow_Dashboard.twbx")
    shutil.copy2(tableau_dir / "Trade_Flow_Dashboard.twb", desktop / "Trade_Flow_Dashboard.twb")
    shutil.copy2(tableau_dir / "HOW_TO_OPEN.md", desktop / "HOW_TO_OPEN.md")
    shutil.copytree(tableau_dir / "Data", desktop / "Data")
    logger.info("Desktop pack: %s", desktop)
    return desktop


def build() -> Path:
    frames = prepare_frames()
    write_extracts(frames)
    twb = build_twb(frames)
    twbx = package_twbx(twb)
    write_howto()
    # README pointer
    (TABLEAU_DIR / "README.md").write_text(
        "See HOW_TO_OPEN.md — Tableau Public requires Hyper extracts.\n"
        f"Open: {twbx.name}\n",
        encoding="utf-8",
    )
    try:
        sync_desktop_pack()
    except OSError as exc:
        logger.warning("Could not sync Desktop pack: %s", exc)
    return twbx


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    build()
