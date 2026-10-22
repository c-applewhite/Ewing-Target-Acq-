"""Google Places (New) Text Search collector.

This module only:

- Calls the Google Places Text Search API
- Handles pagination, retries, and rate limiting
- Converts Google responses into simple dictionaries

It does not persist database records, normalize businesses, remove duplicates,
classify companies, or calculate scores. Those responsibilities belong to the
application pipeline.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import datetime
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


PLACES_SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.types",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)

# Approximately 10 requests per second.
_MIN_INTERVAL_SECONDS = 0.1

# Retry temporary API and network failures up to three times.
_MAX_RETRIES = 3

# Google Places Text Search allows up to 20 results per page.
_PAGE_SIZE = 20

# The API supports a maximum location-bias radius of 50,000 meters.
_MAX_RADIUS_METERS = 50_000


def resolve_api_key() -> str:
    """Resolve the Google Places API key without hardcoding it.

    Preference order:

    1. GOOGLE_PLACES_API_KEY environment variable
    2. Abacus.AI authentication secrets file
    """
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()

    if key:
        return key

    possible_paths = (
        os.path.expanduser("~/.config/abacusai_auth_secrets.json"),
        os.path.join(
            os.getcwd(),
            ".config",
            "abacusai_auth_secrets.json",
        ),
    )

    for path in possible_paths:
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)

            for service in data.values():
                if not isinstance(service, dict):
                    continue

                secrets = service.get("secrets", {})

                for name, entry in secrets.items():
                    normalized_name = name.lower()

                    if (
                        "places" not in normalized_name
                        and "google_places" not in normalized_name
                    ):
                        continue

                    if not isinstance(entry, dict):
                        continue

                    value = str(entry.get("value", "")).strip()

                    if value:
                        return value

        except (
            FileNotFoundError,
            json.JSONDecodeError,
            AttributeError,
            TypeError,
        ):
            continue

    return ""


class RateLimiter:
    """Thread-safe minimum-interval rate limiter."""

    def __init__(
        self,
        min_interval: float = _MIN_INTERVAL_SECONDS,
    ) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        """Wait until another API request may be sent."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call

            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

            self._last_call = time.monotonic()


def haversine_miles(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
) -> float:
    """Calculate straight-line distance between coordinates in miles."""
    earth_radius_miles = 3958.8

    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    calculation = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(delta_lng / 2) ** 2
    )

    return earth_radius_miles * 2 * math.asin(math.sqrt(calculation))


class PlacesCollector:
    """Collect raw place records from Google Places Text Search."""

    def __init__(
        self,
        api_key: Optional[str] = None,
    ) -> None:
        self.api_key = (api_key or resolve_api_key()).strip()

        if not self.api_key:
            raise RuntimeError(
                "Google Places API key is not configured. "
                "Set the GOOGLE_PLACES_API_KEY environment variable."
            )

        self.rate_limiter = RateLimiter()
        self.errors: list[dict[str, Any]] = []

    @staticmethod
    def _validate_search_inputs(
        text_query: str,
        lat: float,
        lng: float,
        radius_meters: float,
    ) -> None:
        """Validate search inputs before calling Google."""
        if not text_query or not text_query.strip():
            raise ValueError("text_query cannot be empty.")

        if not -90 <= lat <= 90:
            raise ValueError("Latitude must be between -90 and 90.")

        if not -180 <= lng <= 180:
            raise ValueError("Longitude must be between -180 and 180.")

        if not 0 < radius_meters <= _MAX_RADIUS_METERS:
            raise ValueError(
                f"radius_meters must be greater than 0 and no more than "
                f"{_MAX_RADIUS_METERS:,}."
            )

    def _record_error(
        self,
        *,
        query: str,
        status: Any,
        message: str,
    ) -> None:
        """Add a structured error to the collector error list."""
        self.errors.append(
            {
                "query": query,
                "status": status,
                "message": message,
                "time": datetime.utcnow().isoformat(),
            }
        )

    def _search_text_page(
        self,
        text_query: str,
        lat: float,
        lng: float,
        radius_meters: float,
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform one Text Search request with retries and backoff."""
        self._validate_search_inputs(
            text_query,
            lat,
            lng,
            radius_meters,
        )

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

        body: dict[str, Any] = {
            "textQuery": text_query.strip(),
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": lat,
                        "longitude": lng,
                    },
                    "radius": float(radius_meters),
                }
            },
            "pageSize": _PAGE_SIZE,
        }

        if page_token:
            body["pageToken"] = page_token

        backoff_seconds = 1.0
        last_status: Any = None
        last_message = "Unknown error"

        for attempt in range(1, _MAX_RETRIES + 1):
            self.rate_limiter.wait()

            try:
                response = requests.post(
                    PLACES_SEARCH_TEXT_URL,
                    headers=headers,
                    json=body,
                    timeout=30,
                )

                if response.status_code == 200:
                    return response.json()

                last_status = response.status_code
                last_message = response.text[:400]

                retryable_statuses = {
                    429,
                    500,
                    502,
                    503,
                    504,
                }

                if response.status_code in retryable_statuses:
                    logger.warning(
                        "Temporary Places API error %s "
                        "(attempt %s of %s) for '%s'.",
                        response.status_code,
                        attempt,
                        _MAX_RETRIES,
                        text_query,
                    )

                    if attempt < _MAX_RETRIES:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2

                    continue

                logger.error(
                    "Places API error %s for '%s': %s",
                    response.status_code,
                    text_query,
                    last_message,
                )

                self._record_error(
                    query=text_query,
                    status=response.status_code,
                    message=last_message,
                )

                return {}

            except requests.RequestException as exc:
                last_status = "network_exception"
                last_message = str(exc)

                logger.warning(
                    "Places API request failed "
                    "(attempt %s of %s) for '%s': %s",
                    attempt,
                    _MAX_RETRIES,
                    text_query,
                    exc,
                )

                if attempt < _MAX_RETRIES:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2

        self._record_error(
            query=text_query,
            status="retries_exhausted",
            message=(
                f"Request failed after {_MAX_RETRIES} attempts. "
                f"Last status: {last_status}. "
                f"Last message: {last_message}"
            ),
        )

        return {}

    def search(
        self,
        text_query: str,
        lat: float,
        lng: float,
        radius_meters: float,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        """Return Places results for one query across available pages."""
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1.")

        # Google Text Search provides no more than three pages.
        pages_to_request = min(max_pages, 3)

        results: list[dict[str, Any]] = []
        page_token: Optional[str] = None

        for page_number in range(1, pages_to_request + 1):
            data = self._search_text_page(
                text_query=text_query,
                lat=lat,
                lng=lng,
                radius_meters=radius_meters,
                page_token=page_token,
            )

            if not data:
                break

            places = data.get("places", [])

            if isinstance(places, list):
                results.extend(places)

            page_token = data.get("nextPageToken")

            if not page_token:
                break

            logger.debug(
                "Waiting for page token before requesting page %s for '%s'.",
                page_number + 1,
                text_query,
            )

            # Google may require a short delay before a new token is usable.
            time.sleep(2)

        return results

    def _search_text_anywhere_page(
        self,
        text_query: str,
        page_token: Optional[str] = None,
        region_code: str = "US",
    ) -> dict[str, Any]:
        """Perform Text Search without a coordinate bias.

        This is used for explicit geographic queries such as:
            Ewing Outdoor Supply in Arizona
        """
        if not text_query or not text_query.strip():
            raise ValueError("text_query cannot be empty.")

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

        body: dict[str, Any] = {
            "textQuery": text_query.strip(),
            "pageSize": _PAGE_SIZE,
            "regionCode": region_code,
        }

        if page_token:
            body["pageToken"] = page_token

        backoff_seconds = 1.0
        last_status: Any = None
        last_message = "Unknown error"

        for attempt in range(1, _MAX_RETRIES + 1):
            self.rate_limiter.wait()

            try:
                response = requests.post(
                    PLACES_SEARCH_TEXT_URL,
                    headers=headers,
                    json=body,
                    timeout=30,
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        self._record_error(
                            query=text_query,
                            status="invalid_json",
                            message=str(exc),
                        )
                        return {}

                    return data if isinstance(data, dict) else {}

                last_status = response.status_code
                last_message = response.text[:400]

                if response.status_code in {429, 500, 502, 503, 504}:
                    logger.warning(
                        "Temporary Places API error %s "
                        "(attempt %s of %s) for '%s'.",
                        response.status_code,
                        attempt,
                        _MAX_RETRIES,
                        text_query,
                    )

                    if attempt < _MAX_RETRIES:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2

                    continue

                self._record_error(
                    query=text_query,
                    status=response.status_code,
                    message=last_message,
                )
                return {}

            except requests.RequestException as exc:
                last_status = "network_exception"
                last_message = str(exc)

                if attempt < _MAX_RETRIES:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2

        self._record_error(
            query=text_query,
            status="retries_exhausted",
            message=(
                f"Request failed after {_MAX_RETRIES} attempts. "
                f"Last status: {last_status}. "
                f"Last message: {last_message}"
            ),
        )

        return {}

    def search_text_anywhere(
        self,
        text_query: str,
        max_pages: int = 3,
        region_code: str = "US",
    ) -> list[dict[str, Any]]:
        """Return places from an explicit text-and-geography query."""
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1.")

        results: list[dict[str, Any]] = []
        page_token: Optional[str] = None

        for _ in range(min(max_pages, 3)):
            data = self._search_text_anywhere_page(
                text_query=text_query,
                page_token=page_token,
                region_code=region_code,
            )

            if not data:
                break

            places = data.get("places", [])

            if isinstance(places, list):
                results.extend(places)

            page_token = data.get("nextPageToken")

            if not page_token:
                break

            time.sleep(2)

        return results

    @staticmethod
    def parse_place(
        place: dict[str, Any],
    ) -> dict[str, Any]:
        """Flatten a Google Place object into RawResult-friendly fields."""
        location = place.get("location") or {}
        display_name = place.get("displayName") or {}

        if isinstance(display_name, dict):
            name = display_name.get("text")
        else:
            name = str(display_name) if display_name else None

        place_types = place.get("types") or []

        return {
            "place_id": place.get("id"),
            "name": name,
            "formatted_address": place.get("formattedAddress"),
            "lat": location.get("latitude"),
            "lng": location.get("longitude"),
            "phone": place.get("nationalPhoneNumber"),
            "website": place.get("websiteUri"),
            "google_category": ", ".join(place_types),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "business_status": place.get("businessStatus"),
            "maps_url": place.get("googleMapsUri"),
            "raw_json": json.dumps(place),
        }


# ---------------------------------------------------------------------------
# ZIP-code geocoding
# ---------------------------------------------------------------------------

GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode_zip(
    zip_code: str,
    api_key: Optional[str] = None,
    timeout: int = 15,
) -> Optional[dict]:
    """Geocode a 5-digit US ZIP code to latitude/longitude.

    Reuses the same Google API key resolution as the Places collector, so no
    new dependency or credential is introduced. Returns ``{"lat", "lng"}`` on
    success, or ``None`` when the ZIP cannot be resolved to coordinates.

    Raises ``GeocodingError`` when no API key is available or the request
    itself fails, so callers can distinguish a configuration/transport failure
    from a simple "not found".
    """
    key = (api_key or resolve_api_key()).strip()

    if not key:
        raise GeocodingError(
            "No Google API key is available for geocoding. "
            "Set the GOOGLE_PLACES_API_KEY environment variable."
        )

    params = {
        "components": f"postal_code:{zip_code}|country:US",
        "key": key,
    }

    try:
        response = requests.get(
            GEOCODE_ENDPOINT,
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GeocodingError(
            f"Geocoding request failed: {exc}"
        ) from exc

    status = data.get("status")

    if status not in ("OK", "ZERO_RESULTS"):
        raise GeocodingError(
            f"Geocoding API returned status '{status}'."
        )

    results = data.get("results") or []

    if not results:
        return None

    top_result = results[0]
    location = (
        top_result
        .get("geometry", {})
        .get("location", {})
    )
    lat = location.get("lat")
    lng = location.get("lng")

    if lat is None or lng is None:
        return None

    # Additive: also surface city/state/county so ZIP-run enrichment can match
    # Census geography. Existing callers only read lat/lng and are unaffected.
    city, state, county = _parse_address_components(
        top_result.get("address_components", [])
    )

    return {
        "lat": float(lat),
        "lng": float(lng),
        "city": city,
        "state": state,
        "county": county,
    }


def _parse_address_components(
    components: list,
) -> tuple:
    """Extract (city, state_abbr, county) from Google address_components."""
    city = None
    state = None
    county = None

    for component in components or []:
        types = component.get("types", [])

        if "locality" in types and not city:
            city = component.get("long_name")
        elif "postal_town" in types and not city:
            city = component.get("long_name")
        elif (
            "administrative_area_level_3" in types
            and not city
        ):
            city = component.get("long_name")

        if "administrative_area_level_1" in types and not state:
            state = component.get("short_name")

        if "administrative_area_level_2" in types and not county:
            county = component.get("long_name")

    return city, state, county


class GeocodingError(RuntimeError):
    """Raised when a geocoding request cannot be completed."""
