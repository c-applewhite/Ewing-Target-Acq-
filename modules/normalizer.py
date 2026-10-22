"""Pure normalization helpers for company and location data.

These functions accept values and return normalized values. They do not access
the database, make network calls, or depend on a particular market.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


LEGAL_SUFFIXES = {
    "llc",
    "inc",
    "incorporated",
    "co",
    "company",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "lp",
    "pllc",
}

LEGAL_SUFFIX_PHRASES = (
    "limited liability company",
    "limited partnership",
)

ADDRESS_ABBREVIATIONS = {
    "st": "street",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "rd": "road",
    "dr": "drive",
    "ln": "lane",
    "hwy": "highway",
    "pkwy": "parkway",
    "ct": "court",
    "pl": "place",
    "cir": "circle",
    "trl": "trail",
    "ter": "terrace",
    "wy": "way",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}


# Retained only for compatibility with existing DFW-specific code.
# Core normalization does not depend on this list.
KNOWN_TX_CITIES = {
    "dallas",
    "fort worth",
    "arlington",
    "plano",
    "frisco",
    "mckinney",
    "denton",
    "lewisville",
    "justin",
    "weatherford",
    "rockwall",
    "waxahachie",
    "irving",
    "garland",
    "grand prairie",
    "mesquite",
    "carrollton",
    "richardson",
    "allen",
    "flower mound",
    "euless",
    "bedford",
    "hurst",
    "grapevine",
    "mansfield",
    "cedar hill",
    "desoto",
    "duncanville",
    "wylie",
    "sachse",
    "burleson",
    "keller",
    "southlake",
    "colleyville",
    "roanoke",
    "little elm",
    "the colony",
    "coppell",
    "farmers branch",
    "addison",
    "balch springs",
}


def _collapse_spaces(value: str) -> str:
    """Replace repeated whitespace with one space."""
    return re.sub(r"\s+", " ", value).strip()


def normalize_name(name: Optional[str]) -> str:
    """Normalize a company name for comparison.

    Examples:
        "ABC Materials, L.L.C." -> "abc materials"
        "Smith & Sons Inc."     -> "smith and sons"
    """
    if not name:
        return ""

    cleaned = name.lower().strip()

    # Removing periods first converts L.L.C. to LLC and Inc. to Inc.
    cleaned = cleaned.replace(".", "")
    cleaned = cleaned.replace("&", " and ")

    # Replace remaining punctuation with spaces.
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = _collapse_spaces(cleaned)

    # Remove multi-word legal suffixes from the end.
    suffix_removed = True

    while suffix_removed and cleaned:
        suffix_removed = False

        for phrase in LEGAL_SUFFIX_PHRASES:
            if cleaned == phrase:
                cleaned = ""
                suffix_removed = True
                break

            if cleaned.endswith(f" {phrase}"):
                cleaned = cleaned[: -len(phrase)].strip()
                suffix_removed = True
                break

    # Remove one or more single-token legal suffixes from the end.
    tokens = cleaned.split()

    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()

    return " ".join(tokens)


def phone_digits(phone: Optional[str]) -> str:
    """Return only the significant digits of a US phone number."""
    if not phone:
        return ""

    digits = re.sub(r"\D", "", str(phone))

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    return digits


def normalize_phone(phone: Optional[str]) -> str:
    """Normalize a valid 10-digit US phone number.

    Invalid or incomplete numbers are returned as digits so the original
    information is not silently discarded.
    """
    digits = phone_digits(phone)

    if not digits:
        return ""

    if len(digits) != 10:
        return digits

    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def normalize_domain(website: Optional[str]) -> str:
    """Extract a lowercase hostname from a website URL.

    Examples:
        "https://www.example.com/about" -> "example.com"
        "example.com"                   -> "example.com"
    """
    if not website:
        return ""

    value = str(website).strip()

    if not value:
        return ""

    if not value.lower().startswith(("http://", "https://")):
        value = f"http://{value}"

    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
    except (TypeError, ValueError):
        return ""

    if not hostname:
        return ""

    hostname = hostname.lower().strip().rstrip(".")

    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname


def normalize_address(address: Optional[str]) -> str:
    """Normalize an address for exact-location comparison.

    Suite, apartment and unit identifiers are intentionally removed because
    Google may include or omit them for the same physical business location.
    """
    if not address:
        return ""

    text = str(address).lower().strip()

    # Remove suite/unit identifiers.
    text = re.sub(
        r"""
        (?:
            \b(?:suite|ste|unit|apt)\.?\s*\#?\s*[\w-]+
            |
            \#\s*[\w-]+
        )
        """,
        " ",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    # Remove punctuation that does not help address matching.
    text = re.sub(r"[.,;:]", " ", text)

    # Standardize common street and direction abbreviations.
    for abbreviation, replacement in ADDRESS_ABBREVIATIONS.items():
        text = re.sub(
            rf"\b{re.escape(abbreviation)}\b",
            replacement,
            text,
            flags=re.IGNORECASE,
        )

    return _collapse_spaces(text)


def normalize_city(city: Optional[str]) -> str:
    """Normalize city formatting without restricting it to a known market."""
    if not city:
        return ""

    cleaned = re.sub(r"[.,]", " ", str(city))
    cleaned = _collapse_spaces(cleaned)

    return cleaned.title()


def normalize_zip(zip_code: Optional[str]) -> str:
    """Return the first five digits of a ZIP or ZIP+4 value."""
    if not zip_code:
        return ""

    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(zip_code))

    return match.group(1) if match else ""


def parse_city_state_zip(
    address: Optional[str],
) -> tuple[str, str, str]:
    """Best-effort extraction of city, state and ZIP from a US address.

    Expected Google format:
        "123 Main St, Dallas, TX 75201, USA"
    """
    if not address:
        return "", "", ""

    address_text = str(address).strip()

    zip_code = normalize_zip(address_text)

    state = ""
    state_match = re.search(
        r"\b([A-Za-z]{2})\s+\d{5}(?:-\d{4})?\b",
        address_text,
    )

    if state_match:
        state = state_match.group(1).upper()

    city = ""

    parts = [
        part.strip()
        for part in address_text.split(",")
        if part.strip()
    ]

    # Find the segment containing "ST ZIP". The prior segment is the city.
    for index, part in enumerate(parts):
        if re.search(
            r"\b[A-Za-z]{2}\s+\d{5}(?:-\d{4})?\b",
            part,
        ):
            if index > 0:
                city = normalize_city(parts[index - 1])
            break

    return city, state, zip_code


def is_known_tx_city(city: Optional[str]) -> bool:
    """Return whether a city is in the legacy DFW-area city list.

    This function is retained for compatibility only. New multi-market logic
    should not use it to accept or reject locations.
    """
    if not city:
        return False

    return city.lower().strip() in KNOWN_TX_CITIES