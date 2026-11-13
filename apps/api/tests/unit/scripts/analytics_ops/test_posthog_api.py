"""The sender's shutdown: every queued write is flushed, and an upload failure is never silent."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from scripts.analytics_ops.posthog_api import Sender


def _sender(*failures: Exception) -> Sender:
    return Sender(MagicMock(), list(failures))


def test_a_send_that_raises_still_flushes_and_keeps_its_own_error() -> None:
    sender = _sender(ConnectionError("upload"))

    with pytest.raises(RuntimeError, match="apply broke"), sender:
        raise RuntimeError("apply broke")

    sender.client.shutdown.assert_called_once_with()


def test_a_clean_send_with_a_failed_upload_stops_the_run() -> None:
    sender = _sender(ConnectionError("upload"))

    with pytest.raises(SystemExit, match="1 PostHog upload"), sender:
        pass

    sender.client.shutdown.assert_called_once_with()


def test_a_clean_send_flushes_and_passes() -> None:
    sender = _sender()

    with sender:
        pass

    sender.client.shutdown.assert_called_once_with()
