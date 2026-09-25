"""
Cross-source deduplication for housing_properties.

The same physical apartment complex legitimately gets picked up by more
than one source — most commonly a county CAD's generic tax-roll parcel
*and* an authoritative program registry (HUD LIHTC, TDHCA HTC, HUD's
multifamily-assisted list) that also covers it. This runs as the last
step of pipelines/housing/run.py, after every source has loaded.

Real case that prompted this (see BACKLOG.md): 1414 Belleview in Dallas
is correctly flagged `lihtc` by HUD's LIHTC database, but Dallas CAD's
tax-roll pipeline also produced a row ~22m away labeled `market_rate` —
not because the property is actually mixed-income, but because
`dallas_cad.py` (like every county-parcel pipeline) hard-codes
`market_rate` for every multifamily parcel it produces; the tax roll has
no subsidy-status field, so it can't know better. Confirmed against real
data: 149 CAD-vs-authoritative-source matches exist across all four
counties, all at real shared addresses (checked up to 200m — even the
far end of that range turned out to be the same complex, just geocoded
from a differently-formatted address string).

**Deliberately excludes `hud_public_housing`.** Its rows are almost
always a single small structure within a larger development (unit
counts are overwhelmingly 1-6 — confirmed: >80% of its rows), not the
whole complex. A CAD parcel or LIHTC/TDHCA row for the same development
often has a far larger unit count for the same address (e.g. one real
case: a public-housing row for "12 units" sits 120-200m from a CAD
parcel covering the same complex at "182 units") — that's one building
inside a multi-building complex, not a duplicate of it. Merging those
would silently delete real, distinct buildings and lose per-building
detail this project doesn't have anywhere else. `hud_lihtc`,
`tdhca_htc`, and `hud_multifamily_assisted` don't have this problem —
their unit counts consistently describe the whole named property.

**Source priority** decides which row survives a match and which
fields it's allowed to backfill from (never overwrite) on the loser:
LIHTC status (`hud_lihtc`/`tdhca_htc`) outranks HUD's more generic
"assisted multifamily" bucket, which outranks a CAD parcel's
context-free `market_rate` default — mirroring food_stores/dedupe.py's
rule that a more specific classification wins over a generic one. Two
sources at the same priority (e.g. hud_lihtc vs tdhca_htc both listing
the same LIHTC property, or two CAD counties whose datasets overlap at
a county line) are broken deterministically: prefer whichever already
has a `total_units` value, else whichever source name sorts first.

Matches form connected components (not just pairs) since the same
property can appear in 3+ sources at once (a real case: one hud_lihtc
row matched three separate hud_multifamily_assisted rows for the same
building, from what look like different historical assistance-contract
records) — the whole group collapses to one surviving row, not just
the first pair found.

Manually-edited rows (including ones a user already deleted through the
map) are excluded from matching entirely, on both sides — a soft
delete or edit a human already made is never a candidate to be
"cleaned up" or overwritten by this pass.
"""
from __future__ import annotations

import logging

from foodaccess.common.geo import grid_key, haversine_meters, neighboring_keys, normalize_name
from foodaccess.storage.database import get_connection

logger = logging.getLogger(__name__)

MATCH_DISTANCE_METERS = 250

# Higher wins. hud_public_housing is intentionally absent — see module docstring.
SOURCE_PRIORITY = {
    "hud_lihtc": 3,
    "tdhca_htc": 3,
    "hud_multifamily_assisted": 2,
    "county_parcel_dallas": 1,
    "county_parcel_tarrant": 1,
    "county_parcel_collin": 1,
    "county_parcel_denton": 1,
}

BACKFILL_FIELDS = ["name", "address", "city", "zip_code", "total_units", "is_senior_housing", "is_subsidized"]


def _find_edges(rows: list[dict]) -> list[tuple[int, int]]:
    """Pairs of row indices judged to be the same physical property."""
    by_cell: dict[tuple, list[int]] = {}
    for i, row in enumerate(rows):
        by_cell.setdefault(grid_key(row["latitude"], row["longitude"]), []).append(i)

    names = [normalize_name(row["name"]) for row in rows]
    edges = []
    seen = set()
    for i, row in enumerate(rows):
        if not names[i]:
            continue
        for key in neighboring_keys(row["latitude"], row["longitude"]):
            for j in by_cell.get(key, []):
                if j <= i or rows[j]["source"] == row["source"] or not names[j]:
                    continue
                pair = (i, j)
                if pair in seen:
                    continue
                seen.add(pair)
                if names[i] not in names[j] and names[j] not in names[i]:
                    continue
                distance = haversine_meters(row["latitude"], row["longitude"], rows[j]["latitude"], rows[j]["longitude"])
                if distance <= MATCH_DISTANCE_METERS:
                    edges.append(pair)
    return edges


def _connected_components(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)
    return [members for members in components.values() if len(members) > 1]


def _pick_survivor(members: list[dict]) -> tuple[dict, list[dict]]:
    """Highest-priority row wins; ties broken deterministically (has a unit
    count, then alphabetically-first source name)."""
    best_score = max((SOURCE_PRIORITY[r["source"]], r["total_units"] is not None) for r in members)
    tied = [r for r in members if (SOURCE_PRIORITY[r["source"]], r["total_units"] is not None) == best_score]
    survivor = min(tied, key=lambda r: r["source"])
    losers = [r for r in members if r is not survivor]
    return survivor, losers


def run() -> int:
    with get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT source, source_id, name, address, city, zip_code, total_units, "
                "is_senior_housing, is_subsidized, latitude, longitude "
                "FROM housing_properties "
                "WHERE is_manually_edited = 0 AND latitude IS NOT NULL AND source IN ({})".format(
                    ", ".join(f"'{s}'" for s in SOURCE_PRIORITY)
                )
            ).fetchall()
        ]

    edges = _find_edges(rows)
    components = _connected_components(len(rows), edges)
    if not components:
        logger.info("Housing deduplication: no cross-source duplicates found")
        return 0

    updates = []
    deletions = []
    for members in components:
        survivor, losers = _pick_survivor([rows[i] for i in members])
        backfilled = dict(survivor)
        for loser in losers:
            for field in BACKFILL_FIELDS:
                if backfilled[field] is None and loser[field] is not None:
                    backfilled[field] = loser[field]
        if backfilled != survivor:
            updates.append(backfilled)
        deletions.extend((loser["source"], loser["source_id"]) for loser in losers)

    with get_connection() as conn:
        if updates:
            conn.executemany(
                """
                UPDATE housing_properties SET
                    name = :name, address = :address, city = :city, zip_code = :zip_code,
                    total_units = :total_units, is_senior_housing = :is_senior_housing,
                    is_subsidized = :is_subsidized
                WHERE source = :source AND source_id = :source_id AND is_manually_edited = 0
                """,
                updates,
            )
        conn.executemany(
            "DELETE FROM housing_properties WHERE source = :source AND source_id = :source_id AND is_manually_edited = 0",
            [{"source": s, "source_id": sid} for s, sid in deletions],
        )

    logger.info(
        "Housing deduplication: merged %d duplicate properties into %d survivors", len(deletions), len(components)
    )
    return len(deletions)


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    run()
