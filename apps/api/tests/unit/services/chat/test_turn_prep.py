"""Turn prep: the work a turn starts at request arrival so it overlaps ingress."""

from unittest.mock import patch

from app.services.chat import turn_prep


def test_prep_starts_the_memory_lanes_query_embedding() -> None:
    with patch.object(turn_prep, "start_query_embedding") as embed:
        turn_prep.start_turn_prep("who am I dating")

    embed.assert_called_once_with("who am I dating")
