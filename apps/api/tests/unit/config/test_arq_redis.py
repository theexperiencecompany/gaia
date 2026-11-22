"""Every ARQ client and the worker reach REDIS_URL with the shared connect deadline."""

from unittest.mock import patch

from arq.connections import RedisSettings

from app.config.arq_redis import arq_redis_settings
from app.constants.db import ARQ_REDIS_CONNECT_TIMEOUT_SECONDS


def test_arq_settings_target_redis_url_with_the_shared_connect_deadline() -> None:
    with patch("app.config.arq_redis.settings.REDIS_URL", "redis://:pw@cache.internal:6390/3"):
        arq = arq_redis_settings()

    assert (arq.host, arq.port, arq.database, arq.password) == ("cache.internal", 6390, 3, "pw")
    assert arq.conn_timeout == ARQ_REDIS_CONNECT_TIMEOUT_SECONDS
    assert arq.conn_timeout != RedisSettings().conn_timeout
