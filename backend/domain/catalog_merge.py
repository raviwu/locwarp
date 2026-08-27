"""Pure three-way resolution for the catalog force-sync.

stdlib only (domain ring). No clock, no I/O, no store access — the caller
supplies the three sides and applies the outcome, so every decision here is
deterministic and unit-testable in isolation.

This module works UPSTREAM of the store merge: it shrinks what the catalog is
allowed to write into a record in the first place, so a value the user edited
is never handed to the merge as "the catalog's opinion". The merge itself
(domain/store_merge.py) resolves per unit since change G, and `Resolution.taken`
is what lets the caller stamp only the units the catalog actually corrected.
"""
from __future__ import annotations

from typing import Any, NamedTuple

# Fields the bundled catalog owns on a bookmark. country_code is deliberately
# absent: it is a cached derivation of lat/lng that enrich_bookmark re-resolves
# on every force-sync, so promising to keep a local value here would be broken
# by the very next statement. Its siblings timezone/city/region were never
# candidates either — the merge arbitrates the SOURCE (lat/lng) and lets the
# derivation follow.
BOOKMARK_MERGE_FIELDS: tuple[str, ...] = (
    "name", "lat", "lng", "address", "category_id",
)

CATEGORY_MERGE_FIELDS: tuple[str, ...] = (
    "name", "color", "sort_order", "start_date", "end_date",
)


class Resolution(NamedTuple):
    """Outcome of resolving one record.

    values    — the resolved value per requested field
    kept      — fields where OUR value was preserved over a differing catalog one
    conflicts — the subset of `kept` where both sides moved, differently
    taken     — fields whose resolved value came FROM theirs

    `taken` drives the re-stamp, and it is a field list rather than the bool
    it used to be because change G stamps per merge unit: a catalog correction
    to `name` must re-stamp the name unit and leave `address` reading as of
    whenever the user last touched it. A bool would force the caller to
    re-stamp every unit and hand this machine a fresh timestamp on fields it
    never changed — which is the revert this whole line of work exists to stop.

    `kept` is not redundant with the other three: "the user edited it and the
    catalog had nothing new to say" and "nobody touched anything" produce an
    identical `values`/`conflicts`/`taken`, and only the first should count
    towards the kept_local the sync reports.
    """

    values: dict[str, Any]
    kept: tuple[str, ...]
    conflicts: tuple[str, ...]
    taken: tuple[str, ...]

    @property
    def changed(self) -> bool:
        """True when any resolved value came from theirs."""
        return bool(self.taken)


def resolve_record(
    base: dict[str, Any] | None,
    ours: dict[str, Any],
    theirs: dict[str, Any],
    fields: tuple[str, ...],
) -> Resolution:
    """Resolve ``fields`` of one record against a three-way comparison.

    ``base`` is the catalog value this machine last applied. When it is None,
    or is missing a field, that field bootstraps as ``base := theirs`` — which
    classifies every already-diverged value as a local edit and preserves it.
    That is the intended first-run behavior: overwriting a real edit is the bug
    being fixed, while passing over a stale catalog value is cosmetic.
    """
    values: dict[str, Any] = {}
    kept: list[str] = []
    conflicts: list[str] = []
    taken: list[str] = []

    for field in fields:
        our_value = ours[field]
        their_value = theirs[field]
        # Bootstrap per field, not per record: a baseline written by an older
        # catalog can legitimately lack an id's newer field.
        base_value = their_value if base is None or field not in base else base[field]

        if our_value == their_value:
            # Nothing to arbitrate — including the second Mac's silent no-op
            # once it has received the peer's applied catalog correction.
            resolved = our_value
        elif our_value == base_value:
            resolved = their_value          # genuine catalog correction
            taken.append(field)
        else:
            resolved = our_value            # local edit wins
            kept.append(field)
            if their_value != base_value:
                conflicts.append(field)

        values[field] = resolved

    return Resolution(values, tuple(kept), tuple(conflicts), tuple(taken))
