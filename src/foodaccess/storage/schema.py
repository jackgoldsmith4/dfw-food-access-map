"""
SQLite table definitions for the food access datastore.

One table per data domain, each keyed by a natural (source, source_id) or
(geoid, year, source) key so re-running a pipeline upserts rather than
duplicates rows. `fetched_at` records when the row was last written so
staleness is visible in the data itself, not just in file timestamps.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS food_stores (
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    name            TEXT,
    store_type      TEXT,
    raw_category    TEXT,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    zip_code        TEXT,
    county_fips     TEXT,
    latitude        REAL,
    longitude       REAL,
    snap_authorized INTEGER,
    fetched_at      TEXT NOT NULL,
    is_manually_edited INTEGER NOT NULL DEFAULT 0,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    edited_at       TEXT,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS tract_demographics (
    tract_geoid              TEXT NOT NULL,
    year                     INTEGER NOT NULL,
    source                   TEXT NOT NULL,
    county_fips              TEXT,
    total_population         INTEGER,
    total_households         INTEGER,
    median_household_income  REAL,
    poverty_count            INTEGER,
    poverty_universe         INTEGER,
    snap_households          INTEGER,
    snap_universe            INTEGER,
    fetched_at               TEXT NOT NULL,
    PRIMARY KEY (tract_geoid, year, source)
);

CREATE TABLE IF NOT EXISTS tract_health_estimates (
    tract_geoid  TEXT NOT NULL,
    measure_id   TEXT NOT NULL,
    measure_name TEXT,
    data_value   REAL,
    year         INTEGER NOT NULL,
    source       TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (tract_geoid, measure_id, year)
);

CREATE TABLE IF NOT EXISTS food_access_atlas (
    tract_geoid              TEXT NOT NULL,
    year                     INTEGER NOT NULL,
    urban                    INTEGER,
    population               INTEGER,
    low_income_low_access    INTEGER,
    pct_low_access_half_mile REAL,
    source                   TEXT NOT NULL,
    fetched_at               TEXT NOT NULL,
    PRIMARY KEY (tract_geoid, year, source)
);

CREATE TABLE IF NOT EXISTS food_insecurity_county (
    county_fips           TEXT NOT NULL,
    year                  INTEGER NOT NULL,
    food_insecurity_rate  REAL,
    source                TEXT NOT NULL,
    fetched_at            TEXT NOT NULL,
    PRIMARY KEY (county_fips, year, source)
);

CREATE TABLE IF NOT EXISTS housing_properties (
    source            TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    name              TEXT,
    property_type     TEXT,
    address           TEXT,
    city              TEXT,
    state             TEXT,
    zip_code          TEXT,
    county_fips       TEXT,
    latitude          REAL,
    longitude         REAL,
    total_units       INTEGER,
    is_senior_housing INTEGER,
    is_subsidized     INTEGER,
    raw_json          TEXT,
    fetched_at        TEXT NOT NULL,
    is_manually_edited INTEGER NOT NULL DEFAULT 0,
    is_deleted        INTEGER NOT NULL DEFAULT 0,
    edited_at         TEXT,
    PRIMARY KEY (source, source_id)
);
"""

# Columns added after a table's first release. init_db() applies these to
# already-existing databases via ALTER TABLE, since CREATE TABLE IF NOT
# EXISTS above is a no-op once the table already exists — without this,
# anyone with a populated database from before manual editing existed would
# never get the new columns.
MIGRATIONS = [
    ("food_stores", "is_manually_edited", "INTEGER NOT NULL DEFAULT 0"),
    ("food_stores", "is_deleted", "INTEGER NOT NULL DEFAULT 0"),
    ("food_stores", "edited_at", "TEXT"),
    ("housing_properties", "is_manually_edited", "INTEGER NOT NULL DEFAULT 0"),
    ("housing_properties", "is_deleted", "INTEGER NOT NULL DEFAULT 0"),
    ("housing_properties", "edited_at", "TEXT"),
]
