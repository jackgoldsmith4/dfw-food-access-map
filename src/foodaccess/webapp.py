"""
Minimal local server for viewing the map and making manual corrections.

Replaces `python -m http.server` as the way to run web/ locally: static
files are served exactly the same, plus a small JSON API. /api/{stores,
housing}/edit and /delete correct a name/type or soft-delete a duplicate
— both write straight to SQLite, marking the row is_manually_edited=1 so
upsert_records() (see storage/database.py) never lets a pipeline re-run
overwrite or resurrect it. /api/housing/track sets personal outreach
tracking (reached_out, notes) — a separate concern from correctness, so
it deliberately skips that flag (see TRACKABLE_FIELDS below). Every
endpoint re-exports the affected GeoJSON file afterward so the static
data stays in sync without a separate export step.

Run with: python -m foodaccess.webapp
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify, request, send_from_directory

from config import settings
from foodaccess.export import geojson as export_geojson
from foodaccess.storage.database import get_connection, init_db, utcnow_iso

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=str(settings.PROJECT_ROOT / "web"), static_url_path="")

# Which fields a human is allowed to change per table, and how to refresh
# that table's exported GeoJSON afterward.
EDITABLE_FIELDS = {
    "food_stores": {"name", "store_type"},
    "housing_properties": {"name", "property_type"},
}
EXPORTERS = {
    "food_stores": export_geojson.export_food_stores,
    "housing_properties": export_geojson.export_housing_properties,
}


def _source_id_from_payload(payload: dict) -> tuple[str, str] | None:
    """(source, source_id) from the request body, or None if either is missing."""
    source, source_id = payload.get("source"), payload.get("source_id")
    return (source, source_id) if source and source_id else None


def _edit(table: str):
    payload = request.get_json(force=True, silent=True) or {}
    ids = _source_id_from_payload(payload)
    if ids is None:
        return jsonify(error="source and source_id are required"), 400
    source, source_id = ids

    updates = {k: v for k, v in payload.items() if k in EDITABLE_FIELDS[table]}
    if not updates:
        return jsonify(error="no editable fields provided"), 400

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE {table} SET {set_clause}, is_manually_edited = 1, edited_at = :edited_at "
            "WHERE source = :source AND source_id = :source_id",
            {**updates, "edited_at": utcnow_iso(), "source": source, "source_id": source_id},
        )
        if cursor.rowcount == 0:
            return jsonify(error="no matching row"), 404

    EXPORTERS[table]()
    return jsonify(ok=True)


# reached_out/notes are personal outreach-tracking metadata, not a
# correction — deliberately doesn't set is_manually_edited/edited_at like
# _edit/_delete do. No pipeline ever writes these two columns (they're not
# part of any HousingProperty record), so upsert_records' dynamic column
# list never touches them regardless of that flag — they're already safe
# from being overwritten by a pipeline re-run.
TRACKABLE_FIELDS = {"reached_out", "notes"}


def _track_housing():
    payload = request.get_json(force=True, silent=True) or {}
    ids = _source_id_from_payload(payload)
    if ids is None:
        return jsonify(error="source and source_id are required"), 400
    source, source_id = ids

    updates = {k: v for k, v in payload.items() if k in TRACKABLE_FIELDS}
    if not updates:
        return jsonify(error="no trackable fields provided"), 400
    if "reached_out" in updates:
        updates["reached_out"] = 1 if updates["reached_out"] else 0

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE housing_properties SET {set_clause} WHERE source = :source AND source_id = :source_id",
            {**updates, "source": source, "source_id": source_id},
        )
        if cursor.rowcount == 0:
            return jsonify(error="no matching row"), 404

    EXPORTERS["housing_properties"]()
    return jsonify(ok=True)


def _delete(table: str):
    payload = request.get_json(force=True, silent=True) or {}
    ids = _source_id_from_payload(payload)
    if ids is None:
        return jsonify(error="source and source_id are required"), 400
    source, source_id = ids

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE {table} SET is_deleted = 1, is_manually_edited = 1, edited_at = :edited_at "
            "WHERE source = :source AND source_id = :source_id",
            {"edited_at": utcnow_iso(), "source": source, "source_id": source_id},
        )
        if cursor.rowcount == 0:
            return jsonify(error="no matching row"), 404

    EXPORTERS[table]()
    return jsonify(ok=True)


@app.post("/api/stores/edit")
def edit_store():
    return _edit("food_stores")


@app.post("/api/stores/delete")
def delete_store():
    return _delete("food_stores")


@app.post("/api/housing/edit")
def edit_housing():
    return _edit("housing_properties")


@app.post("/api/housing/delete")
def delete_housing():
    return _delete("housing_properties")


@app.post("/api/housing/track")
def track_housing():
    return _track_housing()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


def run() -> None:
    init_db()
    app.run(port=8000, debug=False)


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    run()
