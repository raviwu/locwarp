"""Pure diff and merge for BookmarkStore.

No I/O, no side effects, no logger. Two functions only:

- diff_store(current, baseline) -> StoreDiff
- merge_local_wins(remote, local_diff) -> BookmarkStore

Tested separately from BookmarkManager so persistence concerns do not
leak into the merge logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore


@dataclass
class StoreDiff:
    bookmarks_created: list[Bookmark] = field(default_factory=list)
    bookmarks_modified: list[Bookmark] = field(default_factory=list)
    bookmarks_deleted: set[str] = field(default_factory=set)
    categories_created: list[BookmarkCategory] = field(default_factory=list)
    categories_modified: list[BookmarkCategory] = field(default_factory=list)
    categories_deleted: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (
            self.bookmarks_created
            or self.bookmarks_modified
            or self.bookmarks_deleted
            or self.categories_created
            or self.categories_modified
            or self.categories_deleted
        )


def _by_id(items: Iterable) -> dict[str, object]:
    return {x.id: x for x in items}


def diff_store(current: BookmarkStore, baseline: BookmarkStore) -> StoreDiff:
    """Compute id-based diff of current vs baseline."""
    out = StoreDiff()

    cur_b = _by_id(current.bookmarks)
    base_b = _by_id(baseline.bookmarks)
    for bid, bm in cur_b.items():
        if bid not in base_b:
            out.bookmarks_created.append(bm)
        elif bm.model_dump() != base_b[bid].model_dump():
            out.bookmarks_modified.append(bm)
    for bid in base_b:
        if bid not in cur_b:
            out.bookmarks_deleted.add(bid)

    cur_c = _by_id(current.categories)
    base_c = _by_id(baseline.categories)
    for cid, cat in cur_c.items():
        if cid not in base_c:
            out.categories_created.append(cat)
        elif cat.model_dump() != base_c[cid].model_dump():
            out.categories_modified.append(cat)
    for cid in base_c:
        if cid not in cur_c:
            out.categories_deleted.add(cid)

    return out



def merge_local_wins(remote: BookmarkStore, local_diff: StoreDiff) -> BookmarkStore:
    """Apply *local_diff* on top of *remote*, with local intent winning.

    Semantics:
    - created: append if id not already in remote.
    - modified: replace existing by id; if missing (remote deleted it),
      append back so local edits are not lost.
    - deleted: remove from remote; takes precedence over a remote modify.
    """
    out_categories = list(remote.categories)
    out_bookmarks = list(remote.bookmarks)

    cat_index = {c.id: i for i, c in enumerate(out_categories)}
    for cat in local_diff.categories_created:
        if cat.id not in cat_index:
            out_categories.append(cat)
            cat_index[cat.id] = len(out_categories) - 1
    for cat in local_diff.categories_modified:
        if cat.id in cat_index:
            out_categories[cat_index[cat.id]] = cat
        else:
            out_categories.append(cat)
            cat_index[cat.id] = len(out_categories) - 1
    if local_diff.categories_deleted:
        out_categories = [c for c in out_categories if c.id not in local_diff.categories_deleted]
        cat_index = {c.id: i for i, c in enumerate(out_categories)}

    bm_index = {b.id: i for i, b in enumerate(out_bookmarks)}
    for bm in local_diff.bookmarks_created:
        if bm.id not in bm_index:
            out_bookmarks.append(bm)
            bm_index[bm.id] = len(out_bookmarks) - 1
    for bm in local_diff.bookmarks_modified:
        if bm.id in bm_index:
            out_bookmarks[bm_index[bm.id]] = bm
        else:
            out_bookmarks.append(bm)
            bm_index[bm.id] = len(out_bookmarks) - 1
    if local_diff.bookmarks_deleted:
        out_bookmarks = [b for b in out_bookmarks if b.id not in local_diff.bookmarks_deleted]
        bm_index = {b.id: i for i, b in enumerate(out_bookmarks)}

    return BookmarkStore(categories=out_categories, bookmarks=out_bookmarks)
