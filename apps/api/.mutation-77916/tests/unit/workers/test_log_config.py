"""Unit tests for the ARQ CLI custom-log-dict config.

``ARQ_LOG_CONFIG`` is a plain dict handed to arq's ``--custom-log-dict``, which
runs ``logging.config.dictConfig`` on it. The tests pin the contract that
fixes the double-emitted arq lines: version 1, existing loggers survive, and
the ``arq`` logger ends up with no handlers of its own and propagation to the
root interceptor at LOG_LEVEL.
"""

import logging
import logging.config

from app.workers.config.log_config import ARQ_LOG_CONFIG
from shared.py.logging import LOG_CONFIG

ARQ_LOGGER_NAME = "arq"


class TestArqLogConfig:
    def test_config_is_dict(self) -> None:
        assert isinstance(ARQ_LOG_CONFIG, dict)

    def test_version_is_1(self) -> None:
        assert ARQ_LOG_CONFIG["version"] == 1

    def test_existing_loggers_are_not_disabled(self) -> None:
        # The root interceptor and every already-configured GAIA logger must
        # survive the dictConfig call; disabling them would silence the process.
        assert ARQ_LOG_CONFIG["disable_existing_loggers"] is False

    def test_arq_logger_has_no_own_handlers(self) -> None:
        assert ARQ_LOG_CONFIG["loggers"][ARQ_LOGGER_NAME]["handlers"] == []

    def test_arq_logger_propagates_to_root(self) -> None:
        assert ARQ_LOG_CONFIG["loggers"][ARQ_LOGGER_NAME]["propagate"] is True

    def test_arq_level_mirrors_configured_log_level(self) -> None:
        # arq describes our own process, so it belongs on LOG_LEVEL — not on
        # the third-party floor the root logger sits at.
        assert ARQ_LOG_CONFIG["loggers"][ARQ_LOGGER_NAME]["level"] == LOG_CONFIG["level"]

    def test_consumable_by_dict_config_without_adding_handlers(self) -> None:
        arq = logging.getLogger(ARQ_LOGGER_NAME)
        original_handlers = list(arq.handlers)
        original_propagate = arq.propagate
        original_level = arq.level
        logging.config.dictConfig(ARQ_LOG_CONFIG)
        try:
            assert arq.handlers == original_handlers
            assert arq.propagate is True
            assert arq.level == logging.getLevelName(LOG_CONFIG["level"])
        finally:
            arq.handlers = original_handlers
            arq.propagate = original_propagate
            arq.level = original_level
