"""Typed record produced by every food-store source, regardless of origin."""
from dataclasses import dataclass
from typing import Optional

# Normalized store_type values every source's transform step maps into.
GROCERY = "grocery"
MASS_MERCHANDISER = "mass_merchandiser"
CONVENIENCE = "convenience"
OTHER = "other"


@dataclass
class FoodStore:
    source: str            # "usda_snap" | "osm"
    source_id: str
    name: Optional[str]
    store_type: str        # one of GROCERY / MASS_MERCHANDISER / CONVENIENCE / OTHER
    raw_category: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    county_fips: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    snap_authorized: Optional[bool] = None

    def to_row(self, fetched_at: str) -> dict:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "name": self.name,
            "store_type": self.store_type,
            "raw_category": self.raw_category,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "county_fips": self.county_fips,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "snap_authorized": None if self.snap_authorized is None else int(self.snap_authorized),
            "fetched_at": fetched_at,
        }
