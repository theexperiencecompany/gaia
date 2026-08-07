"""Schemathesis property-based fuzzing of the API OpenAPI schema.

Every operation in the schema is driven with generated inputs against the same
test app the endpoint tests use (``tests.conftest._create_test_app``), asserting
no 5xx, no undocumented status codes, and schema-valid responses. Auth comes
from the ``get_current_user`` dependency override, so generated requests
authenticate as the suite's FAKE_USER exactly like the ``client`` fixture.

Scope decision (full schema, no exclusions): narrowing to core CRUD paths does
not reduce the failure wall — the wall is harness-wide, not path-specific.
Observed failure classes as of bootstrap (Aug 2026), none of which are skip-
list candidates:

- Hermetic mode (root conftest's ``USE_REAL_SERVICES`` default ``"0"``) mocks
  ``_get_mongodb_instance`` with a MagicMock; every repository call then 500s
  with "object MagicMock can't be used in 'await' expression". Run with real
  services (``USE_REAL_SERVICES=1`` + Docker infra) for actual signal — the
  same requirement the service/e2e suites have.
- The no-op lifespan never registers lazy providers, so Chroma/LLM-touching
  endpoints 500 with "Provider 'X' not found in registry" — a test-harness
  artifact, not a production path (registration happens in the real lifespan).
- Under real services, the process-global Mongo client (see tests/integration/real/
  conftest.py, ``mongo_db``) latches onto the first event loop it is used
  from; hypothesis runs each example on a fresh loop, so the second request
  on raises "Event loop is closed" and every handler's broad ``except``
  converts it to a 500. Needs the same per-test loop rebinding the service
  suite does — a harness fix, not an app bug.
- The hermetic fence blanks real API keys and injects a fake GOOGLE_API_KEY, so
  embedding-dependent writes (notes, memory, search) fail loudly by design.
- Real findings from the bootstrap run (contract, not crash): schemathesis
  v4's "unsupported methods" check expects 405 for undocumented methods on a
  path, but FastAPI's parameterized routes shadow sibling literal paths and
  return 422 instead (same family as the fixed ``/todos/bulk`` ordering bug);
  Gmail/Calendar endpoints return an undocumented 403 for users without the
  integration connected; OAuth login/callback endpoints return an
  undocumented 307 redirect; ``POST /api/v1/desktop/tool-result`` returns an
  undocumented 410. All are reachable by real users; none are in the schema.

Failures that survive the noise above are real contract bugs; fix or report
them, never silence them.
"""

import os

from hypothesis import settings
import pytest
import schemathesis

from tests.conftest import _create_test_app

app = _create_test_app()
schema = schemathesis.openapi.from_asgi("/openapi.json", app)

pytestmark = pytest.mark.skipif(
    os.environ.get("USE_REAL_SERVICES", "0") != "1",
    reason="needs real services (provider registration + real Mongo); see docstring",
)


@pytest.mark.integration
@schema.parametrize()
@settings(max_examples=20)
def test_api_contract(case) -> None:
    """No server errors and schema-valid responses for fuzzed inputs."""
    case.call_and_validate()
