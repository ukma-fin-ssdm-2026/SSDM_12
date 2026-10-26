"""Lab6 prepared reference: request_ids.py. AI-assisted draft."""

import re
import uuid

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def normalize_request_id(candidate: str | None) -> str:
    """THR-02/09: preserve safe 8..64-character IDs; replace log-unsafe input."""
    safe = candidate is not None and _SAFE_REQUEST_ID.fullmatch(candidate) is not None
    return candidate if safe else uuid.uuid4().hex
