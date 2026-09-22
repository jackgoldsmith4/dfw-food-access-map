"""Typed record for multifamily/senior/public/subsidized housing properties."""
from dataclasses import dataclass
from typing import Optional

PUBLIC_HOUSING = "public_housing"
SUBSIDIZED_MULTIFAMILY = "subsidized_multifamily"
LIHTC = "lihtc"
MARKET_RATE = "market_rate"


@dataclass
class HousingProperty:
    source: str            # "hud_public_housing" | "hud_multifamily_assisted" | "hud_lihtc" | "tdhca" | "county_parcel"
    source_id: str
    name: Optional[str]
    property_type: str     # one of the constants above
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    county_fips: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    total_units: Optional[int]
    is_senior_housing: Optional[bool] = None
    is_subsidized: Optional[bool] = None
    raw_json: Optional[str] = None

    def to_row(self, fetched_at: str) -> dict:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "name": self.name,
            "property_type": self.property_type,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "county_fips": self.county_fips,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "total_units": self.total_units,
            "is_senior_housing": None if self.is_senior_housing is None else int(self.is_senior_housing),
            "is_subsidized": None if self.is_subsidized is None else int(self.is_subsidized),
            "raw_json": self.raw_json,
            "fetched_at": fetched_at,
        }
