#!/usr/bin/env python3
"""
Build a self-contained HTML dashboard from pipeline CSV exports.

Output: outputs/dashboard/Trade_Flow_Dashboard.html
Open in any browser (double-click). No Tableau required.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CSV_DIR = ROOT / "outputs" / "csv"
OUT_DIR = ROOT / "outputs" / "dashboard"
HTML_PATH = OUT_DIR / "Trade_Flow_Dashboard.html"
DOCS_INDEX = ROOT / "docs" / "index.html"

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("html_dashboard")


def load_payload(csv_dir: Path = CSV_DIR) -> dict:
    risk = pd.read_csv(csv_dir / "Risk_Scores.csv").sort_values(
        "composite_risk_0_100", ascending=False
    )
    ports = pd.read_csv(csv_dir / "Port_Risk.csv").sort_values(
        "port_congestion_score_0_100", ascending=False
    )
    anom = pd.read_csv(csv_dir / "Anomalies.csv")
    if "severity_score" in anom.columns:
        anom = anom.sort_values("severity_score", ascending=False)
    else:
        anom = pd.DataFrame(
            columns=["date", "label", "commodity", "direction", "z_score", "severity_score"]
        )
    fc = pd.read_csv(csv_dir / "Forecasts.csv")
    if "model" in fc.columns:
        fc = fc[fc["model"].astype(str) == "ARIMA(1,1,1)"].copy()
    if not fc.empty and "hs_code" in fc.columns:
        top = fc.groupby("hs_code")["historical_12m_import_usd_m"].first().nlargest(6).index
        fc = fc[fc["hs_code"].isin(top)].sort_values(["commodity", "forecast_date"])
    dep = pd.read_csv(csv_dir / "Dependency_Detail.csv")
    if "dependency_score_0_100" in dep.columns:
        dep = dep.sort_values("dependency_score_0_100", ascending=False)
    recs = pd.read_csv(csv_dir / "Recommendations.csv")
    insights = pd.read_csv(csv_dir / "Insights_Narrative.csv")
    clusters = pd.read_csv(csv_dir / "Clusters.csv")
    viz = pd.read_csv(csv_dir / "Visualizations_Data.csv")
    hist = (
        viz[viz["chart"] == "line_top10_imports"].copy()
        if "chart" in viz.columns
        else pd.DataFrame(columns=["series", "x", "y"])
    )

    def short(s: str, n: int = 34) -> str:
        s = str(s)
        return s if len(s) <= n else s[: n - 1] + "…"

    risk = risk.copy()
    risk["label"] = risk["commodity"].map(lambda x: short(x))
    dep = dep.copy()
    dep["label"] = dep["commodity"].map(lambda x: short(x))
    anom = anom.copy()
    anom["label"] = anom["commodity"].map(lambda x: short(x, 28))

    return {
        "kpis": {
            "critical": int((risk["risk_tier"] == "Critical").sum()),
            "elevated": int((risk["risk_tier"] == "Elevated").sum()),
            "anomalies": int(len(anom)),
            "avg_dependency": round(float(risk["dependency_score_0_100"].mean()), 1),
            "max_port": round(float(ports["port_congestion_score_0_100"].max()), 1),
            "recommendations": int(len(recs)),
            "commodities": int(len(risk)),
            "ports": int(len(ports)),
        },
        "risk": risk[
            [
                "label",
                "commodity",
                "composite_risk_0_100",
                "top_supplier",
                "top_supplier_share_pct",
                "risk_tier",
                "critical",
            ]
        ]
        .head(15)
        .to_dict("records"),
        "ports": ports[
            [
                "port",
                "port_congestion_score_0_100",
                "avg_dwell_days",
                "avg_congestion",
                "bottleneck_flag",
            ]
        ].to_dict("records"),
        "anomalies": anom[
            ["date", "label", "commodity", "direction", "z_score", "severity_score"]
        ].to_dict("records"),
        "forecasts": fc[
            ["commodity", "forecast_date", "forecast_import_usd_m", "horizon_month"]
        ].to_dict("records"),
        "dependency": dep[
            [
                "label",
                "commodity",
                "top_supplier",
                "top_supplier_share_pct",
                "dependency_score_0_100",
                "risk_tier",
            ]
        ]
        .head(15)
        .to_dict("records"),
        "recs": recs[
            ["priority", "audience", "theme", "commodity", "recommendation", "expected_impact"]
        ]
        .head(12)
        .to_dict("records"),
        "insights": insights[["section", "narrative"]].to_dict("records"),
        "clusters_country": clusters[clusters["entity_type"] == "country"][
            ["entity_name", "cluster_label", "total_import_12m_usd_m"]
        ].to_dict("records"),
        "hist": hist[["series", "x", "y"]].to_dict("records"),
    }


def render_html(data: dict) -> str:
    payload = json.dumps(data, default=str)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Trade Flow Intelligence Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {{
    --ink: #142033;
    --muted: #5b6577;
    --line: #d7dde7;
    --bg: #f6f4ef;
    --panel: #ffffff;
    --accent: #0e7c7b;
    --warn: #b45309;
    --crit: #9f1239;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    color: var(--ink);
    background:
      radial-gradient(1200px 500px at 10% -10%, #e7eef2 0%, transparent 55%),
      radial-gradient(900px 400px at 100% 0%, #efe8dc 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px 22px 64px; }}
  header {{
    display: grid;
    gap: 8px;
    margin-bottom: 22px;
    padding-bottom: 18px;
    border-bottom: 1px solid var(--line);
  }}
  .brand {{
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 13px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--accent);
    font-weight: 700;
  }}
  h1 {{
    margin: 0;
    font-size: clamp(28px, 4vw, 40px);
    line-height: 1.1;
    font-weight: 600;
  }}
  .sub {{
    margin: 0;
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 14px;
    color: var(--muted);
    max-width: 62ch;
  }}
  .kpis {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 12px;
    margin: 18px 0 26px;
  }}
  .kpi {{
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 14px 14px 12px;
  }}
  .kpi .label {{
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
  }}
  .kpi .value {{
    margin-top: 6px;
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 28px;
    font-weight: 700;
    color: var(--ink);
  }}
  .kpi.crit .value {{ color: var(--crit); }}
  .kpi.warn .value {{ color: var(--warn); }}
  .kpi.ok .value {{ color: var(--accent); }}
  .grid {{
    display: grid;
    grid-template-columns: 1.2fr 1fr;
    gap: 14px;
    margin-bottom: 14px;
  }}
  .grid.three {{ grid-template-columns: 1fr 1fr 1fr; }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 10px 10px 4px;
    min-height: 340px;
  }}
  .panel h2 {{
    margin: 6px 10px 0;
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 13px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 700;
  }}
  .chart {{ width: 100%; height: 300px; }}
  .chart.tall {{ height: 360px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 13px;
  }}
  th, td {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--line);
    vertical-align: top;
  }}
  th {{
    color: var(--muted);
    font-size: 11px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }}
  .tag {{
    display: inline-block;
    padding: 2px 8px;
    border: 1px solid var(--line);
    font-size: 11px;
  }}
  .tag.Critical {{ color: var(--crit); border-color: #f1c0cd; background: #fff5f7; }}
  .tag.Elevated {{ color: var(--warn); border-color: #f0d2a8; background: #fff8ef; }}
  .insight {{
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 16px 18px;
    margin-bottom: 10px;
  }}
  .insight h3 {{
    margin: 0 0 6px;
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 14px;
  }}
  .insight p {{
    margin: 0;
    color: var(--muted);
    line-height: 1.45;
    font-size: 15px;
  }}
  footer {{
    margin-top: 28px;
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-size: 12px;
    color: var(--muted);
  }}
  @media (max-width: 980px) {{
    .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .grid, .grid.three {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">Trade Flow Intelligence</div>
    <h1>U.S. Trade Risk & Flow Dashboard</h1>
    <p class="sub">Built from pipeline CSV exports — supply-chain risk, port congestion, import forecasts, anomalies, and recommendations.</p>
  </header>

  <section class="kpis" id="kpis"></section>

  <section class="grid">
    <div class="panel"><h2>Composite supply-chain risk</h2><div id="riskChart" class="chart tall"></div></div>
    <div class="panel"><h2>Port congestion scores</h2><div id="portChart" class="chart tall"></div></div>
  </section>

  <section class="grid">
    <div class="panel"><h2>Import forecast — top commodities (USD m)</h2><div id="fcChart" class="chart tall"></div></div>
    <div class="panel"><h2>Top supplier concentration (%)</h2><div id="depChart" class="chart tall"></div></div>
  </section>

  <section class="grid three">
    <div class="panel"><h2>Anomaly severity</h2><div id="anomChart" class="chart"></div></div>
    <div class="panel"><h2>Historical imports (top series)</h2><div id="histChart" class="chart"></div></div>
    <div class="panel"><h2>Country clusters by import volume</h2><div id="clusterChart" class="chart"></div></div>
  </section>

  <section class="panel" style="min-height:auto;margin-bottom:14px;">
    <h2>Priority recommendations</h2>
    <div style="overflow:auto;max-height:420px;">
      <table id="recsTable"></table>
    </div>
  </section>

  <section class="panel" style="min-height:auto;margin-bottom:14px;">
    <h2>Risk detail</h2>
    <div style="overflow:auto;max-height:420px;">
      <table id="riskTable"></table>
    </div>
  </section>

  <section>
    <h2 style="font-family:'Avenir Next',sans-serif;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);">Narrative insights</h2>
    <div id="insights"></div>
  </section>

  <footer>Source: outputs/csv · Generated locally from Trade Flow Intelligence Agent</footer>
</div>

<script>
const DATA = {payload};

const layoutBase = {{
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: {{ family: 'Avenir Next, Segoe UI, sans-serif', color: '#142033', size: 12 }},
  margin: {{ l: 120, r: 20, t: 10, b: 40 }},
  hoverlabel: {{ bgcolor: '#142033' }},
}};

function kpiCards() {{
  const k = DATA.kpis;
  const items = [
    ['Critical risks', k.critical, 'crit'],
    ['Elevated risks', k.elevated, 'warn'],
    ['Anomalies', k.anomalies, 'warn'],
    ['Avg dependency', k.avg_dependency, 'ok'],
    ['Max port score', k.max_port, 'ok'],
    ['Recommendations', k.recommendations, ''],
  ];
  document.getElementById('kpis').innerHTML = items.map(([label, value, cls]) =>
    `<div class="kpi ${{cls}}"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`
  ).join('');
}}

function riskChart() {{
  const rows = [...DATA.risk].reverse();
  Plotly.newPlot('riskChart', [{{
    type: 'bar', orientation: 'h',
    y: rows.map(r => r.label),
    x: rows.map(r => r.composite_risk_0_100),
    marker: {{ color: rows.map(r => r.risk_tier === 'Critical' ? '#9f1239' : (r.risk_tier === 'Elevated' ? '#b45309' : '#0e7c7b')) }},
    hovertemplate: '%{{y}}<br>Risk: %{{x}}<extra></extra>',
  }}], {{
    ...layoutBase,
    xaxis: {{ title: 'Composite risk (0–100)', range: [0, 100] }},
    yaxis: {{ automargin: true }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function portChart() {{
  const rows = DATA.ports;
  Plotly.newPlot('portChart', [{{
    type: 'bar',
    x: rows.map(r => r.port),
    y: rows.map(r => r.port_congestion_score_0_100),
    marker: {{ color: '#0e7c7b' }},
    hovertemplate: '%{{x}}<br>Score: %{{y}}<br>Dwell days in hover data<extra></extra>',
    customdata: rows.map(r => r.avg_dwell_days),
  }}], {{
    ...layoutBase,
    margin: {{ l: 50, r: 20, t: 10, b: 80 }},
    xaxis: {{ tickangle: -35, title: 'Port' }},
    yaxis: {{ title: 'Congestion score (0–100)' }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function forecastChart() {{
  const by = {{}};
  DATA.forecasts.forEach(r => {{
    if (!by[r.commodity]) by[r.commodity] = {{ x: [], y: [] }};
    by[r.commodity].x.push(r.forecast_date);
    by[r.commodity].y.push(r.forecast_import_usd_m);
  }});
  const traces = Object.entries(by).map(([name, v]) => ({{
    type: 'scatter', mode: 'lines', name: name.length > 28 ? name.slice(0,27)+'…' : name,
    x: v.x, y: v.y,
  }}));
  Plotly.newPlot('fcChart', traces, {{
    ...layoutBase,
    margin: {{ l: 60, r: 10, t: 10, b: 40 }},
    legend: {{ orientation: 'h', y: -0.25 }},
    xaxis: {{ title: 'Forecast month' }},
    yaxis: {{ title: 'Import value (USD millions)' }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function depChart() {{
  const rows = [...DATA.dependency].slice(0, 12).reverse();
  Plotly.newPlot('depChart', [{{
    type: 'bar', orientation: 'h',
    y: rows.map(r => r.label),
    x: rows.map(r => r.top_supplier_share_pct),
    marker: {{ color: '#1f4e79' }},
    text: rows.map(r => r.top_supplier),
    hovertemplate: '%{{y}}<br>Share: %{{x}}%<br>Supplier: %{{text}}<extra></extra>',
  }}], {{
    ...layoutBase,
    xaxis: {{ title: 'Top supplier share (%)' }},
    yaxis: {{ automargin: true }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function anomChart() {{
  const rows = DATA.anomalies;
  Plotly.newPlot('anomChart', [{{
    type: 'bar',
    x: rows.map(r => r.label),
    y: rows.map(r => r.severity_score),
    marker: {{ color: rows.map(r => r.direction === 'spike' ? '#b45309' : '#9f1239') }},
    hovertemplate: '%{{x}}<br>Severity: %{{y}}<extra></extra>',
  }}], {{
    ...layoutBase,
    margin: {{ l: 40, r: 10, t: 10, b: 90 }},
    xaxis: {{ tickangle: -30, title: 'Commodity' }},
    yaxis: {{ title: 'Severity' }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function histChart() {{
  const by = {{}};
  DATA.hist.forEach(r => {{
    if (!by[r.series]) by[r.series] = {{ x: [], y: [] }};
    by[r.series].x.push(r.x);
    by[r.series].y.push(r.y);
  }});
  // keep top 5 series by last value
  const ranked = Object.entries(by).map(([name, v]) => [name, v, v.y[v.y.length-1] || 0])
    .sort((a,b) => b[2]-a[2]).slice(0,5);
  const traces = ranked.map(([name, v]) => ({{
    type: 'scatter', mode: 'lines', name: name.length > 22 ? name.slice(0,21)+'…' : name,
    x: v.x, y: v.y,
  }}));
  Plotly.newPlot('histChart', traces, {{
    ...layoutBase,
    margin: {{ l: 50, r: 10, t: 10, b: 40 }},
    showlegend: false,
    xaxis: {{ title: 'Month' }},
    yaxis: {{ title: 'USD millions' }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function clusterChart() {{
  const rows = [...DATA.clusters_country].sort((a,b) => b.total_import_12m_usd_m - a.total_import_12m_usd_m).slice(0, 10);
  Plotly.newPlot('clusterChart', [{{
    type: 'bar',
    x: rows.map(r => r.entity_name),
    y: rows.map(r => r.total_import_12m_usd_m),
    marker: {{ color: '#0e7c7b' }},
    text: rows.map(r => r.cluster_label),
    hovertemplate: '%{{x}}<br>%{{y:,.0f}} USD m<br>%{{text}}<extra></extra>',
  }}], {{
    ...layoutBase,
    margin: {{ l: 50, r: 10, t: 10, b: 80 }},
    xaxis: {{ tickangle: -35, title: 'Country' }},
    yaxis: {{ title: '12m imports (USD m)' }},
  }}, {{responsive: true, displayModeBar: false}});
}}

function tables() {{
  const recHead = `<tr><th>#</th><th>Audience</th><th>Theme</th><th>Commodity</th><th>Recommendation</th></tr>`;
  document.getElementById('recsTable').innerHTML = recHead + DATA.recs.map(r =>
    `<tr><td>${{r.priority}}</td><td>${{r.audience||''}}</td><td>${{r.theme||''}}</td><td>${{r.commodity||''}}</td><td>${{r.recommendation||''}}</td></tr>`
  ).join('');

  const riskHead = `<tr><th>Commodity</th><th>Risk</th><th>Tier</th><th>Top supplier</th><th>Share %</th></tr>`;
  document.getElementById('riskTable').innerHTML = riskHead + DATA.risk.map(r =>
    `<tr><td>${{r.commodity}}</td><td>${{r.composite_risk_0_100}}</td><td><span class="tag ${{r.risk_tier}}">${{r.risk_tier}}</span></td><td>${{r.top_supplier}}</td><td>${{r.top_supplier_share_pct}}</td></tr>`
  ).join('');

  document.getElementById('insights').innerHTML = DATA.insights.map(i =>
    `<div class="insight"><h3>${{i.section}}</h3><p>${{i.narrative}}</p></div>`
  ).join('');
}}

kpiCards();
riskChart();
portChart();
forecastChart();
depChart();
anomChart();
histChart();
clusterChart();
tables();
</script>
</body>
</html>
"""


def build() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_payload()
    (OUT_DIR / "_data.json").write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
    html = render_html(data)
    HTML_PATH.write_text(html, encoding="utf-8")
    # Keep GitHub Pages source in sync
    DOCS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    DOCS_INDEX.write_text(html, encoding="utf-8")
    logger.info("Dashboard written: %s", HTML_PATH)
    logger.info("GitHub Pages source: %s", DOCS_INDEX)
    return HTML_PATH


if __name__ == "__main__":
    path = build()
    print(path)
