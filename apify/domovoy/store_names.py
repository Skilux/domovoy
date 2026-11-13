"""Names of the named key-value stores, with an optional per-Actor suffix.

A limited-permission Actor may open only the named stores it created itself. The public Store Actor and the
private demo Actor run under the same Apify account, so the public one sets DOMOVOY_STORE_SUFFIX (push_public.sh)
and keeps its own stores. Unset, the names are the base names the demo Actor has always used.
"""

import os
import re
from collections.abc import Mapping

_SUFFIX = re.compile(r"^(-[a-z0-9]+)*$")


def store_name(base: str, environ: Mapping[str, str] = os.environ) -> str:
    suffix = environ.get("DOMOVOY_STORE_SUFFIX", "")
    if not _SUFFIX.match(suffix):
        raise ValueError("DOMOVOY_STORE_SUFFIX must be empty or lowercase words each led by '-', like '-public'")
    return base + suffix
