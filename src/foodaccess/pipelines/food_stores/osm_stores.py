"""
OpenStreetMap food retailers (via the Overpass API).

Free, ODbL-licensed complement to the USDA SNAP list: it catches
non-SNAP-authorized grocers that the USDA source misses, at the cost of
inconsistent tagging for small independents/convenience stores in DFW.
Used to fill gaps, not as the primary source. Data is ODbL-licensed —
any derived dataset that's published must carry attribution to
OpenStreetMap contributors.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_json
from foodaccess.pipelines.food_stores.models import CONVENIENCE, GROCERY, OTHER, FoodStore
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

SHOP_TAG_MAP = {
    "supermarket": GROCERY,
    "grocery": GROCERY,
    "greengrocer": GROCERY,
    "convenience": CONVENIENCE,
}

_SHOP_TAGS = "|".join(SHOP_TAG_MAP.keys())


def _build_query() -> str:
    south, west, north, east = settings.DFW_BBOX
    bbox = f"{south},{west},{north},{east}"
    return f"""
    [out:json][timeout:180];
    (
      node["shop"~"^({_SHOP_TAGS})$"]({bbox});
      way["shop"~"^({_SHOP_TAGS})$"]({bbox});
    );
    out center tags;
    """.strip()


def fetch() -> dict:
    """Run the Overpass query and return the raw JSON response."""
    logger.info("Querying Overpass API for food retailers in the DFW bounding box")
    return fetch_json(settings.OVERPASS_API_URL, params={"data": _build_query()})


def _normalize_store_type(shop_tag: str | None) -> str:
    if not shop_tag:
        return OTHER
    return SHOP_TAG_MAP.get(shop_tag.strip().lower(), OTHER)


def transform(raw: dict) -> list[FoodStore]:
    """Parse Overpass elements into normalized FoodStore records."""
    stores: list[FoodStore] = []

    for element in raw.get("elements", []):
        tags = element.get("tags", {})

        if "lat" in element and "lon" in element:
            latitude, longitude = element["lat"], element["lon"]
        elif "center" in element:
            latitude, longitude = element["center"].get("lat"), element["center"].get("lon")
        else:
            continue  # no usable coordinates

        shop_tag = tags.get("shop")
        address_parts = [tags.get("addr:housenumber"), tags.get("addr:street")]
        address = " ".join(p for p in address_parts if p) or None

        stores.append(
            FoodStore(
                source="osm",
                source_id=f"{element['type']}/{element['id']}",
                name=tags.get("name"),
                store_type=_normalize_store_type(shop_tag),
                raw_category=shop_tag,
                address=address,
                city=tags.get("addr:city"),
                state=tags.get("addr:state"),
                zip_code=tags.get("addr:postcode"),
                county_fips=None,  # OSM tags don't include county FIPS; resolve via a spatial join later
                latitude=latitude,
                longitude=longitude,
                snap_authorized=None,  # unknown from OSM tags alone
            )
        )

    logger.info("Parsed %d OSM food retailers", len(stores))
    return stores


def store(stores: list[FoodStore]) -> int:
    fetched_at = utcnow_iso()
    rows = [s.to_row(fetched_at) for s in stores]
    count = upsert_records("food_stores", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d OSM store rows", count)
    return count


def run() -> int:
    raw = fetch()
    stores = transform(raw)
    return store(stores)


if __name__ == "__main__":
    run()
