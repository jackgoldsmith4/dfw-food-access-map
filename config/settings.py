"""
Central configuration for the Dallas-Fort Worth food access data pipelines.

Pipeline modules should import paths, endpoints, and geographic scope from
here rather than hardcoding values, so the project's scope (e.g. which
counties count as "the metro") can be changed in one place.

Every URL below has been verified against a real response (see the
comment above each one for when and how) — the only exception is HUD
LIHTC, which requires a one-time manual download because huduser.gov
blocks automated access entirely (see HUD_LIHTC_FILE_PATH and
pipelines/housing/hud_lihtc.py).
"""
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "food_access.db"

RAW_POPULATION_DIR = RAW_DATA_DIR / "population"
RAW_HOUSING_DIR = RAW_DATA_DIR / "housing"
WEB_DATA_DIR = PROJECT_ROOT / "web" / "data"

for _dir in (RAW_POPULATION_DIR, RAW_HOUSING_DIR, WEB_DATA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# --- Geographic scope ------------------------------------------------------
# Dallas-Fort Worth-Arlington MSA county FIPS codes (state prefix 48 = Texas).
# Edit this list to widen/narrow the metro definition.
DFW_COUNTY_FIPS = {
    "48085": "Collin",
    "48113": "Dallas",
    "48121": "Denton",
    "48139": "Ellis",
    "48221": "Hood",
    "48231": "Hunt",
    "48251": "Johnson",
    "48257": "Kaufman",
    "48367": "Parker",
    "48397": "Rockwall",
    "48439": "Tarrant",
    "48497": "Wise",
}
STATE_FIPS = "48"  # Texas

# Rough bounding box around the DFW metro, used to scope OSM Overpass
# queries: (south, west, north, east)
DFW_BBOX = (32.20, -97.65, 33.45, -96.35)

# --- Census / CDC APIs -----------------------------------------------------

CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
# Verified 2026-09: api.census.gov now redirects to an HTML "missing key"
# page even for light/unauthenticated use — treat this as REQUIRED, not
# optional. Get a free key at https://api.census.gov/data/key_signup.html
CENSUS_ACS_YEAR = 2023  # latest ACS 5-year vintage at time of writing
CENSUS_ACS_BASE_URL = f"https://api.census.gov/data/{CENSUS_ACS_YEAR}/acs/acs5"

# CDC PLACES: census-tract-level model estimates dataset on the Socrata
# open-data portal (data.cdc.gov). Verify this is still the current release's
# resource id before running: https://data.cdc.gov/browse?q=PLACES%20census%20tract
CDC_PLACES_TRACT_ENDPOINT = "https://data.cdc.gov/resource/cwsq-ngmh.json"
CDC_APP_TOKEN = os.environ.get("CDC_APP_TOKEN", "")  # optional, raises rate limit

# --- Food retailers ----------------------------------------------------

# USDA SNAP Retailer Locator verified 2026-09: it's a live, queryable
# ArcGIS FeatureServer (found via the DCAT feed at
# https://usda-snap-retailers-usda-fns.hub.arcgis.com/), not a static bulk
# file as originally assumed — see pipelines/food_stores/snap_retailers.py.
USDA_SNAP_RETAILER_QUERY_URL = (
    "https://services1.arcgis.com/RLQu0rK7h4kbsBq5/arcgis/rest/services/"
    "snap_retailer_location_data/FeatureServer/0/query"
)

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

# --- Housing -------------------------------------------------------------

# HUD eGIS Resource Locator FeatureServer query endpoints, verified 2026-09
# via the DCAT feed at https://hudgis-hud.opendata.arcgis.com/. Re-check
# that feed if HUD reorganizes its ArcGIS Online items.
HUD_RESOURCE_LOCATOR_FEATURE_SERVERS = {
    "public_housing": (
        "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/"
        "Public_Housing_Buildings/FeatureServer/0/query"
    ),
    "multifamily_assisted": (
        "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/"
        "MULTIFAMILY_PROPERTIES_ASSISTED/FeatureServer/0/query"
    ),
}

# HUD LIHTC Database — MANUAL DOWNLOAD REQUIRED. huduser.gov's entire
# domain sits behind an AWS WAF JavaScript challenge that returns HTTP 202
# "challenge" to any non-browser client — confirmed blocked for both
# `curl` and `requests`, no automated fetch is possible. Download
# LIHTCPUB.ZIP yourself from
# https://www.huduser.gov/portal/datasets/lihtc/property.html, unzip it,
# and place the extracted folder at RAW_HOUSING_DIR / "lihtcpub" (i.e.
# LIHTCPUB.xlsx should end up at RAW_HOUSING_DIR/lihtcpub/LIHTCPUB.xlsx).
# See pipelines/housing/hud_lihtc.py for the confirmed schema.
HUD_LIHTC_FILE_PATH = "lihtcpub/LIHTCPUB.xlsx"

# TDHCA Housing Tax Credit Property Inventory — verified real URL 2026-09,
# found via the "Apply for Funds" page. A clean, stable Excel file, no
# bot-protection — plain `curl`/`requests` works. 3,356 statewide LIHTC
# properties, 85% already geocoded (Latitude/Longitude columns), updated
# monthly. See pipelines/housing/tdhca_htc.py for the confirmed schema.
TDHCA_HTC_REPORT_URL = "https://tdhca.texas.gov/sites/default/files/multifamily/docs/HTCPropertyInventory_2.xlsx"

# Dallas CAD verified 2026-09: a real, working direct-download link to the
# "current ownership" bulk export (a ZIP of linked CSVs — see
# pipelines/housing/dallas_cad.py for the confirmed schema). DCAD updates
# this file periodically, so treat each pull as a snapshot.
DCAD_CURRENT_ROLL_URL = (
    "https://www.dallascad.org/ViewPDFs.aspx?type=3&id="
    "%5C%5CDCAD.ORG%5CWEB%5CWEBDATA%5CWEBFORMS%5CDATA%20PRODUCTS%5CDCAD2026_CURRENT.ZIP"
)

# Tarrant Appraisal District (TAD) verified 2026-09: real, working
# direct-download links to the pipe-delimited "Standard Distribution"
# export (see pipelines/housing/tarrant_cad.py for the confirmed schema).
# Unlike DCAD this is two separate flat files, not a multi-table ZIP.
TAD_RESIDENTIAL_DATA_URL = "https://www.tad.org/content/data-download/PropertyData(Delimited)_R.ZIP"
TAD_COMMERCIAL_DATA_URL = "https://www.tad.org/content/data-download/PropertyData(Delimited)_C.ZIP"

# Collin CAD verified 2026-09: unlike Dallas/Tarrant, Collin publishes its
# full appraisal roll as a live Socrata dataset on the Texas open data
# portal — queryable directly via the SODA API, no file download needed.
# The dataset id is tied to a specific tax year ("Collin CAD Appraisal
# Data - 2025", last updated 2026-09) — confirm at
# https://collincad.org/open-data-portal/ that a newer id hasn't replaced
# it before assuming this stays current indefinitely.
COLLIN_CAD_SODA_ENDPOINT = "https://data.texas.gov/resource/vffy-snc6.json"

# Denton County verified 2026-09: Denton CAD's own site (dentoncad.com /
# denton.prodigycad.com) is a JS-only SPA with no exposed data API, but
# Denton County's GIS hub publishes the same appraisal data pre-joined to
# parcel polygon geometry in one ArcGIS MapServer layer — the only one of
# the four counties where coordinates come for free, no separate
# geocoding pass needed. See pipelines/housing/denton_cad.py.
DENTON_PARCELS_QUERY_URL = "https://gis.dentoncounty.gov/arcgis/rest/services/Parcels_FC/MapServer/0/query"

# --- Population / food insecurity (form-gated or report-only sources) ------

# USDA SNAP-authorized Retailer Access Map (SRAM) — verified real download
# URL, 2026-09. USDA renamed the classic "Food Access Research Atlas" to
# "Large Retailer Access Map" (LRAM, now stale — last real vintage 2019)
# and introduced SRAM (2025 vintage) alongside it; this pipeline uses
# SRAM. Found via https://www.ers.usda.gov/data-products/food-access-research-atlas/download-the-data
# — re-check that page if USDA publishes a newer vintage under a new URL.
USDA_FOOD_ACCESS_ATLAS_URL = (
    "https://www.ers.usda.gov/media/29394/"
    "2025-snap-authorized-retailer-access-map-sram-data.xlsx"
)

# Feeding America "Map the Meal Gap" — verified 2026-09: Feeding America's
# own published report/request-form path has no stable bulk file, BUT
# their interactive map (map.feedingamerica.org) loads its data from this
# plain JSON endpoint client-side — found by inspecting that page's own
# network requests, confirmed to work with a normal HTTP client (no auth,
# no browser needed). It's undocumented/informal (not an official public
# API Feeding America publishes or supports), so it could change without
# notice — but it's the exact same data their own map displays publicly.
FEEDING_AMERICA_MAPDATA_URL = "https://map.feedingamerica.org/mapdata"
FEEDING_AMERICA_YEAR = 2024  # latest year available as of this writing

# --- HTTP behavior ---------------------------------------------------------

HTTP_TIMEOUT_SECONDS = 30
HTTP_MAX_RETRIES = 3
HTTP_USER_AGENT = "dfw-food-access-map/0.1 (research project)"
