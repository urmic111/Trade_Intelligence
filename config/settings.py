"""Central configuration for the Trade Flow Intelligence Agent."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_CACHE = PROJECT_ROOT / "data" / "cache"
OUTPUTS = PROJECT_ROOT / "outputs"

for _path in (DATA_RAW, DATA_PROCESSED, DATA_CACHE, OUTPUTS):
    _path.mkdir(parents=True, exist_ok=True)

# API keys (optional — pipeline falls back to public/synthetic data)
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", "")
BEA_API_KEY = os.getenv("BEA_API_KEY", "")
DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY", "")

# Data.gov / agency endpoints
DATASETS = {
    "bea_trade": {
        "name": "U.S. International Trade in Goods and Services (BEA)",
        "url": "https://apps.bea.gov/api/data",
        "source": "BEA / Data.gov",
        "format": "json",
    },
    "census_imports_hs": {
        "name": "USA Trade Data – Imports by Country & Commodity (Census HS)",
        "url": "https://api.census.gov/data/timeseries/intltrade/imports/hs",
        "source": "U.S. Census Bureau / Data.gov",
        "format": "json",
    },
    "census_exports_hs": {
        "name": "USA Trade Data – Exports by Country & Commodity (Census HS)",
        "url": "https://api.census.gov/data/timeseries/intltrade/exports/hs",
        "source": "U.S. Census Bureau / Data.gov",
        "format": "json",
    },
    "bts_ports": {
        "name": "Port-Level Trade Statistics (BTS)",
        "url": "https://data.bts.gov/resource/k5sy-ie2e.json",
        "source": "Bureau of Transportation Statistics / Data.gov",
        "format": "json",
    },
    "commerce_supply_chain": {
        "name": "Supply Chain Disruption Data (Commerce)",
        "url": "https://api.census.gov/data/timeseries/intltrade/imports/porths",
        "source": "U.S. Department of Commerce / Data.gov",
        "format": "json",
    },
    "itc_tariffs": {
        "name": "Tariff & Duty Schedules (ITC)",
        "url": "https://dataweb.usitc.gov/trade/search/Import/HTS",
        "source": "U.S. International Trade Commission / Data.gov",
        "format": "html",
    },
    "usda_commodity": {
        "name": "Global Commodity Flow Data (USDA + Census)",
        "url": "https://api.census.gov/data/timeseries/intltrade/exports/usda",
        "source": "USDA / Census / Data.gov",
        "format": "json",
    },
}

# Analytics parameters
FORECAST_HORIZON_MONTHS = 12
TOP_N_COMMODITIES = 20
ANOMALY_ZSCORE_THRESHOLD = 2.5
RANDOM_SEED = 42
HTTP_TIMEOUT = 30
HTTP_MAX_RETRIES = 3
HTTP_RETRY_BACKOFF = 2.0

# Major trading partners & HS chapter proxies for synthetic fallback
COUNTRIES = [
    "China", "Mexico", "Canada", "Japan", "Germany", "South Korea",
    "Vietnam", "India", "Taiwan", "United Kingdom", "Brazil", "France",
    "Italy", "Netherlands", "Thailand", "Malaysia", "Singapore",
    "Australia", "Saudi Arabia", "Switzerland",
]

COMMODITIES = [
    {"hs": "8542", "name": "Electronic Integrated Circuits", "critical": True},
    {"hs": "8703", "name": "Motor Cars & Vehicles", "critical": False},
    {"hs": "2709", "name": "Crude Petroleum Oils", "critical": True},
    {"hs": "3004", "name": "Medicaments Packaged", "critical": True},
    {"hs": "8517", "name": "Telephone Sets & Network Equipment", "critical": True},
    {"hs": "8471", "name": "Automatic Data Processing Machines", "critical": True},
    {"hs": "2711", "name": "Petroleum Gases", "critical": True},
    {"hs": "8708", "name": "Motor Vehicle Parts", "critical": False},
    {"hs": "9018", "name": "Medical Instruments", "critical": True},
    {"hs": "7208", "name": "Flat-Rolled Iron/Steel", "critical": False},
    {"hs": "2902", "name": "Cyclic Hydrocarbons", "critical": False},
    {"hs": "7108", "name": "Gold Unwrought", "critical": False},
    {"hs": "1005", "name": "Maize (Corn)", "critical": False},
    {"hs": "1201", "name": "Soya Beans", "critical": False},
    {"hs": "2601", "name": "Iron Ores & Concentrates", "critical": True},
    {"hs": "2804", "name": "Hydrogen, Rare Gases, Silicon", "critical": True},
    {"hs": "8507", "name": "Electric Accumulators", "critical": True},
    {"hs": "9401", "name": "Seats", "critical": False},
    {"hs": "3901", "name": "Polymers of Ethylene", "critical": False},
    {"hs": "6109", "name": "T-shirts & Singlets", "critical": False},
    {"hs": "2844", "name": "Radioactive Chemical Elements", "critical": True},
    {"hs": "8112", "name": "Beryllium, Chromium, Germanium etc.", "critical": True},
    {"hs": "2615", "name": "Niobium, Tantalum, Vanadium Ores", "critical": True},
    {"hs": "8504", "name": "Electrical Transformers", "critical": False},
    {"hs": "8802", "name": "Aircraft & Spacecraft", "critical": True},
]

PORTS = [
    "Los Angeles", "Long Beach", "New York/Newark", "Savannah",
    "Houston", "Seattle", "Oakland", "Charleston", "Norfolk", "Miami",
]

OUTPUT_WORKBOOK = OUTPUTS / "Trade_Flow_Intelligence_Report.xlsx"
