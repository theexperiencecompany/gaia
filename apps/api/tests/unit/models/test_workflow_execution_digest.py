"""The recorded result digest: bounded without lying about what came back."""

import json

import pytest

from app.models.workflow_execution_models import build_result_digest, largest_list_len

pytestmark = pytest.mark.unit


class TestADigestNeverShedsAListToNothing:
    def test_one_oversized_element_is_cut_harder_rather_than_dropped(self) -> None:
        """Five wide messages under a 1.2 KB bound used to come out as
        ``{"data":{"messages":[]}}``: the first element did not fit even after
        the first string trim, so every element was shed and a full result was
        recorded as an empty one, which the empty-result checks then believed."""
        wide = {"id": "m1", **{f"field_{n}": "x" * 9_000 for n in range(8)}}
        huge = {"data": {"messages": [wide] * 5}}

        digest = build_result_digest(json.dumps(huge), max_chars=1_200)

        assert len(digest) <= 1_200
        assert largest_list_len(json.loads(digest)) >= 1

    def test_a_result_that_fits_is_recorded_whole(self) -> None:
        small = {"data": {"messages": [{"id": "m1"}, {"id": "m2"}]}}

        assert json.loads(build_result_digest(json.dumps(small), max_chars=1_200)) == small
