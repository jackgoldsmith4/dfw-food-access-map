# DFW Food Access Map — Data Pipelines

ETL pipelines that pull and store the raw data behind the Dallas-Fort Worth
food access map: food retailer locations, tract-level demographics/health,
and multifamily/subsidized housing locations.

## Structure

```
config/settings.py          Central config: paths, DFW county scope, API/file URLs
src/foodaccess/
  common/http_client.py     Shared HTTP layer (fetch_json, download_file, fetch_arcgis_features)
  common/logging_config.py  Shared logging setup
  storage/schema.py         SQLite table definitions
  storage/database.py       Connection handling + generic upsert
  pipelines/food_stores/    USDA SNAP retailers, OpenStreetMap, cross-source deduplication
  pipelines/population/     Census ACS, CDC PLACES, USDA Food Access Atlas, Feeding America
  pipelines/housing/        HUD Resource Locator, HUD LIHTC, TDHCA, Dallas/Tarrant/Collin/Denton CAD parcels
  geocoding/census_geocoder.py  Fills in lat/long for addresses that don't have it (Census Bulk Geocoder)
  export/geojson.py         Exports SQLite -> web/data/*.geojson for the map frontend
  cli.py                    Run one or all pipeline domains
data/raw/                   Downloaded source files, as-is (gitignored)
data/processed/             Reserved for later export steps (e.g. vector tiles)
data/food_access.db         SQLite datastore (gitignored, rebuilt by the pipelines)
web/index.html              The map itself (MapLibre GL, no build step)
web/data/                   Generated GeoJSON the map reads (gitignored, rebuilt by `export`)
```

Each source module follows the same three-step shape so fetching, cleaning,
and storing stay independently testable and swappable:

- `fetch()` — pulls raw data from the source (API call or file download) and
  returns it untouched (or a path to the downloaded file). No cleaning here.
- `transform(raw)` — parses/cleans the raw data into a list of typed
  dataclass records, scoped to the DFW metro.
- `store(records)` — upserts the records into SQLite.
- `run()` — calls the three in sequence; this is what a domain's `run.py`
  orchestrator and the CLI call.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # add a free Census API key — required, see .env.example
```

## Running

```bash
python -m foodaccess.cli food_stores
python -m foodaccess.cli population
python -m foodaccess.cli housing
python -m foodaccess.cli geocode   # run after housing — fills in lat/long for CAD parcels
python -m foodaccess.cli export    # run last — writes web/data/*.geojson from the current database
python -m foodaccess.cli all       # runs all of the above, in the right order
```

## Viewing the map

```bash
python -m foodaccess.webapp
```

Then open http://localhost:8000. This runs a small local Flask server
(`src/foodaccess/webapp.py`) that serves `web/` exactly like a static
file server, plus a handful of JSON endpoints the map uses to persist
manual corrections — see "Manual editing" below. (The older
`cd web && python3 -m http.server 8000` still works for read-only
viewing, but editing/deleting from the map requires `webapp`.)

MapLibre GL is loaded from a CDN, no build step. The map reads the two
GeoJSON files `export` produces — food stores (triangles) and housing
properties (squares), each clustered, color-coded by type, and clickable
for details. Each of the 4 sub-categories per layer (e.g. grocery, LIHTC)
has its own checkbox, so any combination can be shown at once (e.g. only
grocery/mass-merchandiser stores and LIHTC housing) — the parent
"Food stores"/"Housing" checkbox selects/deselects all of its
sub-categories at once and shows an indeterminate (–) state when only
some are checked. Unchecking a category re-clusters the map, not just
hides points, so cluster counts stay accurate to what's actually checked.
A "Min. units" number field in the Housing section additionally hides
properties with a known unit count below that value (properties with an
*unknown* unit count — most CAD-parcel-sourced ones — are kept rather
than hidden, since we can't tell whether they'd pass). A "Search by
name" box above both layers filters either one to points whose name
contains the search text (case-insensitive) — typing "tom thumb" leaves
only Tom Thumb stores on the map; an unnamed point can never match a
non-empty search, so it drops out too. Combines with the category
checkboxes and Min. units, not a replacement for them. Re-run `export`
any time the underlying data changes and refresh the page; no server
restart needed.

### Manual editing

A housing point's popup shows its joined tract-level fields formatted
for reading, not raw joined values — median income as `$81,969`, poverty
and SNAP rates as percentages (derived client-side from the
count/universe pairs `export/geojson.py` provides, not stored as a rate
directly), and the tract's own GEOID as "Census tract". This is
`popupViewHTML()`'s `FIELD_FORMATTERS`/`SKIP_FIELDS` in `index.html` — it
only touches keys that exist on housing (`tract_*`); a store popup falls
through to the same generic key-to-label rendering as before, unaffected.

Clicking a point opens a popup with **Edit** and **Delete** buttons.
Edit changes the name and category (store_type/property_type); Delete
soft-removes the point from the map. Both call `webapp.py`'s API, which
writes straight to SQLite and marks the row `is_manually_edited = 1` (a
delete also sets `is_deleted = 1`), then re-runs `export` for that
table so the static GeoJSON stays in sync immediately — no separate
export step needed after an edit.

That flag is what makes edits durable: `upsert_records()`
(`storage/database.py`) checks it before writing any batch, and skips
any row whose `(source, source_id)` is already flagged — so re-running
a pipeline can never silently overwrite a correction, and can never
resurrect a row that was soft-deleted as a duplicate. The food-store
dedup step (`dedupe.py`), which writes with its own SQL rather than
through `upsert_records()`, excludes manually-edited rows from its
matching in the same way. `export`'s query also excludes
`is_deleted = 1` rows outright, so a deletion disappears from the map
on the next export/refresh.

### Outreach tracking

Below Edit/Delete, a housing property's popup has a **Reached out**
checkbox (auto-saves on toggle) and a **Notes** button (opens a free-text
editor in the same popup). Both call `/api/housing/track`, a separate
endpoint from `/edit`/`/delete` — deliberately: marking outreach status
isn't a data correction, so it never sets `is_manually_edited`. No
pipeline ever writes `reached_out`/`notes` (they're not part of any
`HousingProperty` record), so `upsert_records()`'s dynamic column list
never touches them regardless of that flag — they're already immune to
being overwritten by a pipeline re-run without needing the same
protection edits rely on.

"View outreach tracker" opens `outreach.html`, listing every property
currently marked reached-out, with its notes, a **View on map** button
(the same `index.html?type=housing&source=..&source_id=..` deep link the
ranking pages use), an **Edit notes** button (a modal, same data as the
map popup's), and a **Remove** button that unmarks `reached_out` without
erasing its notes — so re-adding it later doesn't lose that history.

A "Toggle food access heatmap" checkbox (off by default) overlays every
location's straight-line distance to the nearest *currently-checked* food
store — green ≤ 1 mile, yellow 1–3 miles, red beyond. It's computed
client-side as a raster image (not thousands of vector circles, since
MapLibre's circle-radius is in screen pixels, not real-world miles) using
a spatially-bucketed nearest-neighbor search, and recomputes automatically
whenever a store category checkbox changes — unchecking "convenience,"
for example, visibly grows the red zones since those stores stop
counting. It sits below the store/housing pins in the paint order so
they stay visible and clickable on top of it.

No choropleth yet (that needs census tract *boundary geometry*, which
isn't pulled — `tract_geoid` and each tract's centroid, via
`geocoding/tract_lookup.py` and `pipelines/population/tract_geometry.py`,
are enough to join and rank tract-level data but not to draw tract
shapes). The heatmap and the two opportunity rankings
(below) are the derived/computed layers built on top of the raw point
data so far.

### Housing opportunity ranking

"View housing opportunity ranking" (top of the map panel) opens
`opportunity.html` — a ranked list of housing properties, for deciding
where improved food access would matter most.

`market_rate` properties are excluded entirely, not scored — only
`public_housing`, `subsidized_multifamily`, and `lihtc` are ranked
(~2,100 properties). Each is scored on six factors, every one converted
to a **percentile rank** (0-1) across that eligible set rather than raw
min-max scaling, so a handful of outlier mega-complexes can't compress
everyone else's score toward one end of the scale:

1. Distance to the nearest grocery/mass-merchandiser store (further =
   higher opportunity) — *all* such stores count here, not just
   whichever categories happen to be checked on the main map.
2. Total units (more units = higher opportunity — more households
   affected by fixing this one location).
3. Tract median household income (lower = higher opportunity).
4. Tract poverty rate.
5. Tract SNAP participation rate.
6. Tract USDA low-access rate (SRAM's own `pct_low_access_half_mile` —
   a direct cross-check against this project's own distance metric,
   from an entirely different measurement approach).

A slider per factor (0-10, default 5 = equal weighting) lets you
reweight live: `score = Σ(slider_weight × percentile)`, recomputed and
re-sorted instantly on every drag. This works client-side with no
server round-trip because percentiles and raw values (distance, tract
data) are computed once at page load — only the weighted sum and sort
need to rerun per slider move. `is_senior_housing` shows as a badge on
each row but deliberately isn't part of the score — a "Senior housing
only" checkbox filters the displayed rows to it instead, the same
"narrow the view, don't rescale the ranking" convention as the tract
page's search box: scores/percentiles are always computed against the
full eligible set regardless of the checkbox.

Deliberately left out of the score: county-level Feeding America food
insecurity (only 12 distinct values across the whole metro — doesn't
differentiate between properties in the same county) and CDC PLACES
obesity rate (a downstream health outcome shaped by far more than food
access alone).

### Tract opportunity ranking

"View tract opportunity ranking" opens `opportunity_tracts.html` — the
same idea as the housing ranking, but for a whole census tract
regardless of whether any specific housing property sits there. This is
the page that answers this project's original framing most directly:
not "which existing complex needs help" but "which *area* is
underserved" — relevant beyond just where subsidized housing happens to
already exist (e.g. for deciding where a new store would do the most
good).

All 1,718 DFW-metro tracts are ranked (no filter — every tract is
eligible, unlike housing's market-rate exclusion) by centroid, on the
same percentile-rank/slider-weighted design as the housing ranking:

1. Distance from the tract's centroid to the nearest grocery/mass-
   merchandiser store.
2. **Population density** (`total_population / land_sqmi`) — not just
   total population, since "densely populated" was part of this
   project's brief from the very first data-source research pass, and a
   raw population count can't distinguish a dense urban tract from a
   sparse rural one of the same population. Land area comes from
   `pipelines/population/tract_geometry.py`, pulled from the Census
   Bureau's 2020 Gazetteer file (also the source of each tract's
   centroid) — a different Census product from the Bulk Geocoder used
   elsewhere, since a Gazetteer file already has every tract's centroid
   and land area in one small bulk download rather than needing a
   one-at-a-time API call per tract.
3. Median household income (lower = higher opportunity).
4. Poverty rate.
5. SNAP participation rate.
6. USDA low-access rate.

Same scoring mechanics as the housing page (percentile rank per metric,
slider-weighted sum, instant client-side re-rank) — see that section
above for the fuller rationale.

A "Search by tract number or county" box filters which tracts are
*displayed*, case-insensitive substring match against the GEOID or its
county name (a tract has no "name" the way a store/housing property
does). Scores and percentiles are always computed against all 1,718
tracts regardless of the search box, so a tract's ranking reflects its
standing across the whole metro — search only narrows the view, the same
way the map's category checkboxes filter without rescaling anything.

### Jumping from a ranked list to the map

Clicking any row on either ranking page opens the map centered on that
exact property or tract (`index.html?type=housing&source=..&source_id=..`,
`type=stores`, or `type=tract&geoid=..`). For a property, the map also
isolates its category — checking only that one and unchecking the rest
in its group — and clears the Min. units filter, so the target is never
hidden by (or lost among) whatever was checked before, then opens the
same edit/delete popup a real click would. A tract has no boundary
polygon in this project (only a centroid and land area — see above), so
it's shown as a marker at the
centroid plus a dashed circle sized from land area
(`radius = sqrt(land_sqmi / π)`) — an honest size guide, not a claim
about the tract's actual, usually irregular, shape.

## Source status

Every source below has been run against real, live data at least once
(2026-09) — all 12 sources across all 4 domains work. HUD LIHTC is the one
exception to full automation: huduser.gov blocks automated access
entirely, so it needs a one-time manual download (see its row below), but
its pipeline is fully implemented and tested against the real file.

| Domain | Source | Status |
|---|---|---|
| Food stores | USDA SNAP retailers | **Fully implemented and verified** (2026-09) — it's a live ArcGIS FeatureServer, not a bulk file as originally assumed; 4,513 real DFW-metro retailers found |
| Food stores | OpenStreetMap (Overpass) | Fully implemented, no config needed |
| Food stores | Cross-source dedup (`dedupe.py`) | **Fully implemented and verified** (2026-09) — the same physical store legitimately appears in both sources sometimes (e.g. Whole Foods, Kroger), and USDA's own store-type classification is occasionally wrong (that Whole Foods was "Super Store" -> mass_merchandiser in USDA's data). Matches by proximity + name overlap, keeps the USDA row (for its `snap_authorized`/`county_fips`) but applies OSM's classification. Match distance is per store format, not one constant — 500m for grocery/mass-merchandiser (sparse; a real Kroger was geocoded 257m apart between sources) but a tighter 150m for convenience stores (dense enough that a wide radius risks merging two distinct nearby locations of the same chain — confirmed this pattern in real data before narrowing it). 1,264 duplicates merged in a real run. |
| Population | Census ACS 5-Year | Fully implemented; **requires** `CENSUS_API_KEY` in `.env` (verified 2026-09 — api.census.gov now rejects unauthenticated requests) |
| Population | Tract geometry (`population/tract_geometry.py`) | **Fully implemented and verified** (2026-09) — Census Bureau 2020 Gazetteer file for Texas, no key, no batching needed (one small plain-text download). All 1,718 DFW tracts matched, giving each a centroid (for the tract opportunity ranking's distance metric) and land area (for population density). |
| Population | CDC PLACES (obesity) | Fully implemented |
| Population | USDA SNAP-authorized Retailer Access Map (SRAM) | **Fully implemented and verified** (2026-09) — USDA renamed the classic Atlas to "LRAM" (now stale, 2019 vintage) and introduced SRAM (2025 vintage) as the current product; this pipeline uses SRAM's driving-distance access measures instead. 1,718 real DFW tracts parsed, 89 flagged low-income-low-access. |
| Population | Feeding America (food insecurity) | **Fully implemented and verified** (2026-09) — found their interactive map's own undocumented JSON endpoint (`map.feedingamerica.org/mapdata`), which needs no auth/form. All 12 DFW counties captured; Dallas highest at 19.2%, Rockwall lowest at 10.8% |
| Housing | HUD Resource Locator (public housing + assisted multifamily) | **Fully implemented and verified** (2026-09). `is_senior_housing` was fixed 2026-09-24: previously derived from `IS_202_811_IND`, a combined program-eligibility flag that conflates Section 202 (elderly) with Section 811 (people *under* 62 with disabilities) — confirmed real DFW cases (e.g. "Accessible Residences," 100% disabled residents) were wrongly flagged senior by that alone. Now uses `PCT_AGE62PLUS`, the actual measured elderly share (≥80% = senior, matching the Housing for Older Persons Act's legal threshold; real bimodal distribution — 25 properties under 20% elderly, 47 over 95%) for both `hud_public_housing` (previously never set at all) and `hud_multifamily_assisted`. Left `None` rather than guessed when no percentage is on file. |
| Housing | HUD LIHTC database (`hud_lihtc.py`) | **Fully implemented and verified** (2026-09) against the real file. **Requires a one-time manual download** (huduser.gov blocks all automated access — see below); also required switching to the `python-calamine` engine since `openpyxl` can't parse HUD's export (it contains an invalid OOXML attribute). `is_senior_housing` fixed 2026-09-24: HUD's own data dictionary defines `TRGT_ELD` as 1=Yes/2=No/0-or-blank=Not indicated, but the pipeline was treating any non-1 value (including blank) as "No" — nearly half of all national LIHTC records have no value here at all, and were being confidently asserted as not-senior instead of unknown. |
| Housing | TDHCA HTC Property Inventory (`tdhca_htc.py`) | **Fully implemented and verified** (2026-09) — clean, stable Excel file, no bot-protection, updated monthly. `is_senior_housing` uses the direct "Population Served" field — more reliable than HUD's inferred program flags since TDHCA states the target population outright. Broadened 2026-09-24 to also count "Elderly Limitation"/"Elderly Preference" (not just an exact "Elderly" match) and to leave missing values unknown rather than "not senior." |
| Housing | Dallas CAD parcels (`dallas_cad.py`) | **Fully implemented and verified** (2026-09) — 20,798 multifamily parcels / ~361k units from DCAD's linked CSVs (SPTD B11/B12). No coordinates in the bulk export — addresses are captured for the geocoding pipeline. |
| Housing | Tarrant CAD parcels (`tarrant_cad.py`) | **Fully implemented and verified** (2026-09) — 11,063 multifamily parcels from TAD's pipe-delimited export (Property_Class B/BC). No unit-count field and no zip code exist in this source at all (confirmed, not a parsing gap). No coordinates. |
| Housing | Collin CAD parcels (`collin_cad.py`) | **Fully implemented and verified** (2026-09) — 4,577 multifamily parcels queried live from Collin's Socrata open-data API (propCategoryCode='B'), no file download needed. Full address+zip; unit count present for ~1 in 6 parcels. No coordinates. |
| Housing | Denton County parcels (`denton_cad.py`) | **Fully implemented and verified** (2026-09) — 4,223 multifamily parcels (stateCodes B1/B2) from Denton County's GIS ArcGIS layer. **The only one of the four with real coordinates already included** (parcel-polygon vertex-average), since appraisal data is pre-joined to geometry here. No unit-count field. |
| Housing | Cross-source dedup (`housing/dedupe.py`) | **Fully implemented and verified** (2026-09) — the same complex often gets picked up by a county CAD's generic tax-roll parcel *and* an authoritative registry (HUD LIHTC, TDHCA HTC, HUD's multifamily-assisted list) that also covers it; CAD's `market_rate` is a hard-coded default with no real subsidy-status data behind it, so it always loses to whichever authoritative source matches. Real case that prompted this: 1414 Belleview in Dallas is correctly `lihtc` per HUD's LIHTC database, but Dallas CAD also produced a `market_rate` row ~22m away for the same building. Matches form connected components, not just pairs (one real case: a single hud_lihtc row matched three separate hud_multifamily_assisted rows for the same property). **Deliberately excludes `hud_public_housing`** — its rows are almost always one building within a larger development (unit counts are overwhelmingly 1-6), not the whole complex, so merging them against a project-level CAD/LIHTC/TDHCA row would silently delete real, distinct buildings. 454 duplicates merged into 328 survivors in a real run. |
| Geocoding | Census Bulk Geocoder (`geocoding/census_geocoder.py`) | **Fully implemented and verified** (2026-09) — free, no key, batches up to 10,000 addresses per request. Tested end-to-end against real Dallas CAD rows: 25/25 matched. Real match rates won't be 100% (a legitimate apartment address failed to match in testing) — unmatched addresses are logged, not silently dropped, and simply keep `latitude`/`longitude` as `NULL` for a future retry. |
| Geocoding | Housing-point-to-tract lookup (`geocoding/tract_lookup.py`) | **Fully implemented and verified** (2026-09) — same free Census Geocoder, but its per-coordinate `/geographies/coordinates` endpoint (no bulk form exists for coordinates), used to fill `housing_properties.tract_geoid` for the opportunity score's tract-level context. One-time backfill of all 40,920 rows: **100% matched, 0 not found** — cleaner than the address geocoder's match rate, since it isn't dependent on address-string quality. Run with a small thread pool (8 workers) since it's a real ~4.7-hour job at one request per row otherwise; not included in `cli.py`'s `all` command on purpose (see `BACKGROUND_ONLY`), since every run after the first backfill only looks up newly-added rows and finishes in seconds. |

## Manual download required: HUD LIHTC

Every other source is fully automated. This one isn't — huduser.gov's
entire domain sits behind an AWS WAF JavaScript challenge that blocks
`curl` and `requests` outright (confirmed by direct test), so there's no
way to script around it. One-time setup:

1. Go to https://www.huduser.gov/portal/datasets/lihtc/property.html
2. Click the `LIHTCPUB.ZIP` link and download it
3. Unzip it and place the extracted folder at `data/raw/housing/lihtcpub/`
   (so `LIHTCPUB.xlsx` ends up at `data/raw/housing/lihtcpub/LIHTCPUB.xlsx`)

`hud_lihtc.py`'s `fetch()` just checks that file exists — no further setup
needed, and it doesn't need re-downloading unless you want a newer vintage
(HUD updates it roughly annually).

## Notes

- **Two real bugs found and fixed during a full end-to-end validation pass
  (2026-09)**, both worth knowing about if something looks wrong later:
  - `config/settings.py` never actually called `load_dotenv()` — `.env`
    was silently ignored the whole time, so `CENSUS_API_KEY` only ever
    worked if it happened to already be a real shell environment
    variable. Fixed by loading it at the top of `settings.py`.
  - `download_file()` treated any 2xx response as success, including a
    bot-protection "challenge" response (HTTP 202, empty body) from
    huduser.gov — it wrote a silent 0-byte file that only failed later
    with a confusing "not a valid zip" error. Fixed to raise a clear
    error immediately when a download comes back empty.
- Google Places API is intentionally not used as a bulk source — its ToS
  prohibits storing/displaying results beyond 30 days on a non-Google map,
  which conflicts with a persistent public dataset. It's fine for one-off
  manual verification, just not for this pipeline.
- `DFW_COUNTY_FIPS` in `config/settings.py` defines the metro's scope —
  widen/narrow it there if you want the 13-county CSA instead of the
  12-county MSA, or a tighter core-counties-only view.
- Only 4 of the 12 DFW-metro counties have a CAD parcel pipeline so far
  (Dallas, Tarrant, Collin, Denton — the largest/most urban ones). The
  other 8 (Ellis, Hood, Hunt, Johnson, Kaufman, Parker, Rockwall, Wise)
  are smaller/more rural and haven't been inspected; each would need the
  same source-finding-and-schema-inspection work the first four got.
- `fetch_arcgis_features` (in `common/http_client.py`) paginates by however
  many features a page actually returns, not by the requested page size —
  some hosted ArcGIS services cap responses at their own `maxRecordCount`
  (confirmed: USDA's SNAP retailer service caps at 1000 regardless of what's
  requested), and pagination that assumes otherwise silently truncates
  results.
- Dallas, Tarrant, and Collin parcels have addresses but no coordinates
  from their source — run `python -m foodaccess.cli geocode` after
  `housing` to fill those in via the Census Bulk Geocoder. Denton's source
  already includes parcel geometry, so it's plot-ready as-is.
- TDHCA's HTC inventory and HUD's national LIHTC database substantially
  overlap (same underlying tax-credit deals, different agencies tracking
  them) — expect the same physical property to appear twice, once per
  source. Deduplicating across sources (by address/name matching) is a
  data-quality step for the compute stage, not handled at ingestion time.
- The Feeding America pipeline uses an undocumented endpoint discovered by
  inspecting their own interactive map's network traffic, not a published
  API — it's the same public data their map displays, but unlike every
  other source here it could change or disappear without notice.
- HUD's LIHTC export is malformed OOXML (an invalid `synchVertical`
  attribute) that crashes `openpyxl` outright — confirmed across the
  latest openpyxl release too, not a version issue. `hud_lihtc.py` reads
  it with the `calamine` pandas engine instead, which tolerates it fine.
  If a future HUD export fixes this, `pd.read_excel(..., engine="calamine")`
  would still work unchanged, so no need to special-case it later.
