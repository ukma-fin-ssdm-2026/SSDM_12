"""Generated malformed JSON must produce a validation problem, never a server error."""

import base64
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api.errors import ApiProblem, ErrorCode
from api.pagination import decode_cursor


@settings(max_examples=100, derandomize=True)
@given(item_id=st.one_of(st.none(), st.integers(), st.lists(st.integers(), max_size=4)))
def test_non_string_cursor_id_is_always_validation_error(item_id):
    payload = {"s": "2026-10-20T09:00:00Z", "i": item_id}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    with pytest.raises(ApiProblem) as problem:
        decode_cursor(encoded)

    assert problem.value.code is ErrorCode.VALIDATION_FAILED
    assert problem.value.extensions["errors"][0]["field"] == "query.cursor"
