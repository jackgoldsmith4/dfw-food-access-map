"""Typed records for the population/demographic/health pipelines."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TractDemographics:
    tract_geoid: str
    year: int
    county_fips: Optional[str]
    total_population: Optional[int]
    total_households: Optional[int]
    median_household_income: Optional[float]
    poverty_count: Optional[int]
    poverty_universe: Optional[int]
    snap_households: Optional[int]
    snap_universe: Optional[int]
    source: str = "census_acs5"

    def to_row(self, fetched_at: str) -> dict:
        return {**self.__dict__, "fetched_at": fetched_at}


@dataclass
class TractHealthEstimate:
    tract_geoid: str
    measure_id: str
    measure_name: Optional[str]
    data_value: Optional[float]
    year: int
    source: str = "cdc_places"

    def to_row(self, fetched_at: str) -> dict:
        return {**self.__dict__, "fetched_at": fetched_at}


@dataclass
class FoodAccessAtlasRecord:
    tract_geoid: str
    year: int
    urban: Optional[int]
    population: Optional[int]
    low_income_low_access: Optional[int]
    pct_low_access_half_mile: Optional[float]
    source: str = "usda_food_access_atlas"

    def to_row(self, fetched_at: str) -> dict:
        return {**self.__dict__, "fetched_at": fetched_at}


@dataclass
class FoodInsecurityCounty:
    county_fips: str
    year: int
    food_insecurity_rate: Optional[float]
    source: str = "feeding_america"

    def to_row(self, fetched_at: str) -> dict:
        return {**self.__dict__, "fetched_at": fetched_at}
