"""
Thin HTTP layer shared by every pipeline's fetch step.

Pipelines should never call `requests` directly — routing all network I/O
through here keeps retry/timeout/logging behavior consistent and gives us
one place to change it later (e.g. add caching or swap HTTP libraries).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests

from config import settings

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Raised when a remote source can't be retrieved after retries."""


def _request_with_retries(method: str, url: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("timeout", settings.HTTP_TIMEOUT_SECONDS)
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("User-Agent", settings.HTTP_USER_AGENT)

    last_exc: Exception | None = None
    for attempt in range(1, settings.HTTP_MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            wait = min(2 ** attempt, 30)
            logger.warning(
                "Request failed (attempt %d/%d) for %s: %s — retrying in %ds",
                attempt, settings.HTTP_MAX_RETRIES, url, exc, wait,
            )
            if attempt < settings.HTTP_MAX_RETRIES:
                time.sleep(wait)

    raise FetchError(f"Failed to fetch {url} after {settings.HTTP_MAX_RETRIES} attempts") from last_exc


def fetch_json(url: str, params: dict | None = None, headers: dict | None = None) -> Any:
    """GET a URL and parse the response body as JSON.

    Some APIs (e.g. Census) respond 200/302 with an HTML error page instead
    of a clean 4xx when a required parameter like an API key is missing —
    `raise_for_status()` won't catch that, so we surface the body snippet
    here instead of letting a bare JSONDecodeError obscure the real cause.
    """
    response = _request_with_retries("GET", url, params=params, headers=headers)
    try:
        return response.json()
    except ValueError as exc:
        snippet = response.text[:300]
        raise FetchError(
            f"Response from {response.url} was not valid JSON (status {response.status_code}). "
            f"Body started with: {snippet!r}"
        ) from exc


def fetch_text(url: str, params: dict | None = None, headers: dict | None = None) -> str:
    """GET a URL and return the response body as text (e.g. Overpass QL results)."""
    response = _request_with_retries("GET", url, params=params, headers=headers)
    return response.text


def post_json(url: str, data: dict | None = None, headers: dict | None = None) -> Any:
    """POST form data to a URL and parse the response body as JSON."""
    response = _request_with_retries("POST", url, data=data, headers=headers)
    return response.json()


def post_multipart(url: str, files: dict, data: dict | None = None, timeout: int | None = None) -> str:
    """POST multipart/form-data (e.g. a file upload) and return the raw response text.

    Used for the Census Bulk Geocoder, which accepts a CSV file upload
    rather than JSON. `timeout` can override the default — a large batch
    upload can legitimately take minutes to process server-side.
    """
    kwargs: dict[str, Any] = {"files": files, "data": data}
    if timeout is not None:
        kwargs["timeout"] = timeout
    response = _request_with_retries("POST", url, **kwargs)
    return response.text


def download_file(url: str, dest_path: Path, chunk_size: int = 1 << 16) -> Path:
    """Stream a URL to disk. Used for bulk CSV/Excel/ZIP/PDF downloads.

    A bot-protection "challenge" response (e.g. huduser.gov's AWS WAF) can
    come back as HTTP 202 with an empty body — a 2xx status that
    raise_for_status() won't catch, silently writing a 0-byte file that
    only fails later with a confusing "not a valid zip/excel" error.
    Checked here instead, right where the real cause is visible.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    response = _request_with_retries("GET", url, stream=True)

    size = 0
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                size += len(chunk)
                f.write(chunk)

    if size == 0:
        dest_path.unlink()
        raise FetchError(
            f"Download from {url} returned an empty body (status {response.status_code}) — "
            "likely a bot-protection challenge page rather than the real file."
        )

    logger.info("Downloaded %s -> %s (%d bytes)", url, dest_path, size)
    return dest_path


def fetch_arcgis_features(base_query_url: str, where: str = "1=1", out_fields: str = "*",
                            page_size: int = 2000, extra_params: dict | None = None) -> list[dict]:
    """
    Page through an ArcGIS FeatureServer/MapServer `.../query` endpoint and
    return the combined list of GeoJSON-style features.

    Many hosted ArcGIS services silently cap `resultRecordCount` at their
    own server-side `maxRecordCount` (often 1000) regardless of what's
    requested here — confirmed against a real service that returned
    exactly 1000 records when 2000 were asked for. Treating "got fewer
    than requested" as "no more data" is therefore wrong and silently
    truncates results on any server with a lower cap than `page_size`.
    Instead, keep paging by however many were actually returned each time,
    and stop only when a page comes back empty.
    """
    features: list[dict] = []
    offset = 0

    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "f": "geojson",
            "resultRecordCount": page_size,
            "resultOffset": offset,
        }
        if extra_params:
            params.update(extra_params)

        page = fetch_json(base_query_url, params=params)
        page_features = page.get("features", [])
        features.extend(page_features)

        logger.debug("Fetched %d features (offset=%d) from %s", len(page_features), offset, base_query_url)

        if not page_features:
            break
        offset += len(page_features)

    return features
