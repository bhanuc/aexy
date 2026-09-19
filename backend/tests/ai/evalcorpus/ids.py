"""Stable identifiers for corpus rows.

Every row is named by a slug, and its id is derived from that slug, so the same
corpus gets the same ids on every machine and a generated eval case can name a
ticket by id without the id having been written down anywhere.

The ids avoid being all digits. SQLAlchemy's non-native `Uuid` stores CHAR(32)
with the hyphens stripped, and SQLite's numeric affinity reads an all-digit id
back as a float — the same trap `demo_login_service.DEMO_DEVELOPER_ID` documents.
A SHA-1 digest is overwhelmingly likely to contain a letter already; `_letterise`
makes it certain rather than likely, because "overwhelmingly likely" is how you
get a test that fails once a year.
"""

from __future__ import annotations

import uuid

# Fixed, and never reused for anything else: changing it renumbers the whole
# corpus, which invalidates every generated case that names an id.
NAMESPACE = uuid.UUID("f1e2d3c4-b5a6-4798-8a9b-0c1d2e3f4a5b")


def _letterise(hex32: str) -> str:
    """Guarantee a letter in each hyphen-separated group."""
    groups, cursor = [], 0
    for width in (8, 4, 4, 4, 12):
        chunk = hex32[cursor : cursor + width]
        if chunk.isdigit():
            chunk = "a" + chunk[1:]
        groups.append(chunk)
        cursor += width
    return "-".join(groups)


def corpus_id(kind: str, slug: str) -> str:
    """The id for `slug` within `kind` — e.g. `corpus_id("ticket", "sd-bug-1")`.

    `kind` keeps namespaces apart, so a ticket and an account may share a slug
    without colliding.
    """
    return _letterise(uuid.uuid5(NAMESPACE, f"{kind}/{slug}").hex)
