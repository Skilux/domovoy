"""Dedup keys: the portal:source_id key, property_id, street normalization and distance."""

import base64
import hashlib
import re
import unicodedata
from math import asin, cos, radians, sin, sqrt

from domovoy.models import GeoPoint, Listing

EARTH_RADIUS_M = 6_371_000.0


def listing_key(listing: Listing) -> str:
    return f"{listing.portal}:{listing.source_id}"


def new_property_id(key: str) -> str:
    """p-<10 base32 characters> of sha256(key). Only the first key seen for a new flat is hashed."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return "p-" + base64.b32encode(digest).decode("ascii")[:10]


def normalize_street(street: str | None) -> str | None:
    """A comparable street name: no diacritics, no case, no "ulice", "ul." or "č.p.".

    A trailing house number is dropped. Returns None when nothing is left, so a missing street
    never matches another one.
    """
    if street is None:
        return None
    decomposed = unicodedata.normalize("NFKD", street.casefold())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = re.sub(r"\bc\.\s*p\.", " ", folded)
    folded = re.sub(r"\bulice\b|\bul\.", " ", folded)
    folded = re.sub(r"(\s+\d+(/\d+)?[a-z]?)+\s*$", "", folded)
    return " ".join(re.findall(r"[0-9a-z]+", folded)) or None


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """Haversine distance in metres."""
    phi_a, phi_b = radians(a.lat), radians(b.lat)
    d_phi = radians(b.lat - a.lat)
    d_lambda = radians(b.lon - a.lon)
    h = sin(d_phi / 2) ** 2 + cos(phi_a) * cos(phi_b) * sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))
