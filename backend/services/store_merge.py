"""Re-export shim — the CRDT merge rule moved to domain/store_merge.py (Phase 4a).
Preserves the 5 importers (services/bookmarks.py, services/route_store.py,
services/sync_merge.py, merge_backup.py, tests/test_store_merge.py). Only
test_store_merge.py imports TOMBSTONE_RETENTION_DAYS; the rest import merge_stores."""
from domain.store_merge import merge_stores, TOMBSTONE_RETENTION_DAYS  # noqa: F401

__all__ = ["merge_stores", "TOMBSTONE_RETENTION_DAYS"]
