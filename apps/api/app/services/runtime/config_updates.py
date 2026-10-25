"""Cross-pod notice that runtime configuration changed, so every pod drops its cached copy.

A save applies on the saving pod first, then publishes its scope here;
app/core/runtime_config_subscriber.py applies it on every other pod.
"""

import json

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log

RUNTIME_CONFIG_CHANNEL = "gaia:runtime-config-updated"

# Scope of one provider's credential: PROVIDER_SCOPE_PREFIX + provider name.
PROVIDER_SCOPE_PREFIX = "provider:"
COMPOSIO_AUTH_CONFIGS_SCOPE = "composio_auth_configs"
INSTANCE_TOOLKITS_SCOPE = "instance_toolkits"


async def publish_config_update(scope: str) -> None:
    """Tell every other pod the scope changed; a failed publish is logged, local state stands.

    The caches it would have dropped expire within their 60s TTL anyway.
    """
    client = redis_cache.redis
    if client is None:
        return
    try:
        await client.publish(RUNTIME_CONFIG_CHANNEL, json.dumps({"scope": scope}))
    except Exception as e:
        log.error(
            f"{LogTag.API} Failed to publish runtime-config update",
            channel=RUNTIME_CONFIG_CHANNEL,
            scope=scope,
            error=str(e),
            error_type=type(e).__name__,
        )
