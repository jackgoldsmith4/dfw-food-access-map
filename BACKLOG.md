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
