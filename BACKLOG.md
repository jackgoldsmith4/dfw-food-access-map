# Backlog

Future work not yet built. Not prioritized/ordered — just tracked so it
doesn't get lost.

- **`hud_public_housing` granularity is unresolved.** Its rows are
  individual buildings within a larger development (unit counts are
  overwhelmingly 1-6), while every other housing source is project-level.
  Deliberately excluded from `housing/dedupe.py` for that reason (merging
  a building into a project-level row would delete real, distinct
  structures) — but that means the same development can still show one
  dot per building *plus* one project-level dot from CAD/LIHTC/TDHCA,
  which is still visual clutter for a large complex. Fixing this needs a
  different relationship than dedup's "same point, keep one" — more like
  grouping buildings under their parent development for display, which
  HUD's dataset doesn't give a direct foreign key for (would need to
  infer it from name-prefix + proximity, e.g. "Wahoo Frazier" building
  rows vs "Wahoo Frazier Townhomes" project row).

## Done

- **Manual verification/editing UI.** ~~A way to review and correct
  individual food stores / housing properties directly from the map~~ —
  built: clicking a point now opens Edit/Delete controls in its popup.
  See "Manual editing" in the README.

- **Manual edits must survive pipeline re-runs.** ~~Today every pipeline's
  `store()` step does a full upsert...~~ — built: edited/deleted rows are
  flagged `is_manually_edited` and `upsert_records()` skips them on every
  future pipeline write (and `dedupe.py`'s own SQL does the same). A
  soft-delete flag (`is_deleted`) means a removed duplicate is excluded
  from export/the map but never gets silently recreated by a fresh pull.

- **Cross-source dedup for housing_properties.** ~~`food_stores` has
  `dedupe.py`... `housing_properties` has no equivalent~~ — built:
  `pipelines/housing/dedupe.py`, run as the last step of the housing
  pipeline. Real case that prompted this: 1414 Belleview (Dallas) is
  correctly `lihtc` per HUD's LIHTC database, but Dallas CAD's tax-roll
  pipeline also produced a `market_rate` row ~22m away for the same
  building — CAD's classification is a hard-coded default with no real
  subsidy-status data behind it, so it always loses to whichever
  authoritative source (LIHTC/TDHCA/HUD-assisted) matches. 454
  duplicates merged into 328 survivors in a real run. See the README's
  Source status table and the module docstring for the full matching
  rule, including why `hud_public_housing` is deliberately excluded
  (tracked separately above).

- **Housing-point-to-census-tract lookup.** ~~Nothing links a housing
  point's lat/lon to a tract GEOID yet~~ — built: `geocoding/tract_lookup.py`,
  using the Census Geocoder's per-coordinate `/geographies/coordinates`
  endpoint (no bulk endpoint exists for coordinates, unlike the
  address-batch geocoder). One-time backfill of all 40,920 rows completed
  2026-09-22 with a small thread pool (the one deliberate exception to
  this project's otherwise-sequential pipeline style, since it's a cost
  paid exactly once — routine reruns only look up newly-added rows,
  sequentially, in well under a minute) — **100% matched, 0 not found**,
  a cleaner result than the address-batch geocoder gets, since it isn't
  dependent on address-string quality. Not wired into `cli.py`'s `all`
  command on purpose (see that file's `BACKGROUND_ONLY` set) so a routine
  refresh never silently takes hours.

- **Housing "opportunity score" + ranked list UI tab.** Built together,
  2026-09-22:
  - `export/geojson.py`'s housing export now joins in each property's
    tract-level context (median household income, poverty rate, SNAP
    participation rate, USDA SRAM's low-access rate) via `tract_geoid`.
  - `web/opportunity.html` (linked from the main map) filters to
    `public_housing`/`subsidized_multifamily`/`lihtc` only — `market_rate`
    is a hard exclusion, never scored. For the remaining ~2,100
    properties it computes, once at page load: distance to the nearest
    grocery/mass-merchandiser store (all such stores, not just
    currently-checked ones — confirmed with the user, a deliberate
    difference from the main map's heatmap), total units, and the four
    tract-level fields above. Each is converted to a percentile rank
    (0-1) across that eligible set — robust to outliers, and the reason
    scoring can't be a pure "one row in, one score out" function: a
    percentile is only meaningful relative to the whole set, so the real
    shape is a shared per-metric percentile table (built once) plus a
    per-row function that combines it with the current slider weights.
    Six sliders (one per scored metric, 0-10, default 5) reweight the sum
    live — verified in-browser that dragging a slider re-sorts the list
    instantly with no server round-trip, since only the weighted sum and
    re-sort need to rerun, not the distance calc or percentiles.
  - `is_senior_housing` shown as a badge on each row, deliberately not
    part of the score.
  - Deliberately left out of the score: county-level Feeding America food
    insecurity (only 12 distinct values across the whole metro — doesn't
    differentiate between properties in the same county) and CDC PLACES
    obesity rate (a downstream health outcome shaped by far more than
    food access — would muddy the metric rather than sharpen it).

- **Tract-level opportunity ranking.** The housing ranking answers "which
  existing complex needs help"; this answers this project's original
  framing more directly — "which *area* is underserved," independent of
  whether housing already exists there. Built 2026-09-22:
  - `pipelines/population/tract_geometry.py` pulls the Census Bureau's
    2020 Gazetteer file for Texas (a small bulk plain-text download, not
    another one-at-a-time API call) to get every DFW tract's centroid and
    land area — all 1,718 matched. `export/geojson.py`'s new
    `export_tracts()` joins that with `tract_demographics`/
    `food_access_atlas` into `tracts.geojson`, one point per tract at its
    centroid.
  - `web/opportunity_tracts.html` ranks all 1,718 tracts (no filter —
    every tract is eligible) on the same percentile-rank/slider design as
    the housing page: distance from centroid to nearest grocery/mass
    store, population **density** (`total_population / land_sqmi` — not
    raw population, since "densely populated" was this project's framing
    from the very first data-source research pass and a raw count can't
    tell a dense urban tract from a sparse rural one of the same
    population), median income, poverty rate, SNAP rate, USDA low-access
    rate.

- **Click a list row to jump to it on the map.** Both ranking pages'
  rows now link to `index.html?type=housing&source=..&source_id=..` (or
  `type=stores`, or `type=tract&geoid=..`), handled by `handleDeepLink()`
  in `index.html`. For a housing/store row: the map isolates that
  category — checking it and unchecking every other category in the same
  group (and clearing Min. units for housing), refined 2026-09-22 from an
  earlier version that only force-checked the target's category and left
  the rest alone — flies to it, and opens its normal edit/delete popup —
  `openFeaturePopup()` was split out of the click handler specifically so
  this and a real click open the exact same popup. For a tract row: since
  tracts have no boundary
  polygon in this project (only a centroid + land area), the map instead
  drops a marker at the centroid and draws a dashed circle sized from the
  tract's real land area (`radius = sqrt(land_sqmi / pi)`) as an honest
  approximate size guide — clearly labeled as such in its popup, not
  presented as the tract's actual (usually irregular) shape.

- **Search-by-name filter on the map.** A text box above the layer
  toggles filters food stores and housing to points whose name contains
  the search text, case-insensitive (`matchesSearch()` in `index.html`,
  combined with — not replacing — the category checkboxes and Min.
  units). An unnamed point can't match a non-empty search, so it's
  excluded rather than shown by default. Verified live: "tom thumb"
  correctly narrows 5,898 stores down to exactly the 76 real Tom Thumb
  locations, matches regardless of case, and clearing the box restores
  the full set.
