"""The bounded retry for a Mongo call whose failure costs more than a few seconds of waiting."""

from pymongo.errors import PyMongoError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.constants.db import (
    MONGO_TRANSIENT_RETRY_ATTEMPTS,
    MONGO_TRANSIENT_RETRY_INITIAL_SECONDS,
    MONGO_TRANSIENT_RETRY_MAX_SECONDS,
)

# Iterate a .copy() per call: a tenacity controller carries per-call state.
# Re-raises the last PyMongoError once the attempts run out.
TRANSIENT_MONGO_RETRY = AsyncRetrying(
    stop=stop_after_attempt(MONGO_TRANSIENT_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(
        initial=MONGO_TRANSIENT_RETRY_INITIAL_SECONDS, max=MONGO_TRANSIENT_RETRY_MAX_SECONDS
    ),
    retry=retry_if_exception_type(PyMongoError),
    reraise=True,
)
