"""Dedup (WP6): cross-portal matcher, stable property_id map, per-profile state.

Order in the run: load_property_ids, merge (updates the ids in place), diff, record_run, then the
two saves. Once extraction has run, the caller sets each flat's commission figures with
flat.model_copy(update={"cross_source": cross_source(flat.sources, commissions)}).
"""

from domovoy.dedup.matcher import cross_source, merge, same_flat
from domovoy.dedup.state import (
    PROFILE_STATE_STORE,
    PROPERTY_IDS_STORE,
    KeyValueStore,
    content_hash,
    diff,
    load_profile_state,
    load_property_ids,
    record_run,
    save_profile_state,
    save_property_ids,
)

__all__ = [
    "PROFILE_STATE_STORE",
    "PROPERTY_IDS_STORE",
    "KeyValueStore",
    "content_hash",
    "cross_source",
    "diff",
    "load_profile_state",
    "load_property_ids",
    "merge",
    "record_run",
    "same_flat",
    "save_profile_state",
    "save_property_ids",
]
