"""Run one call against a user's connector: credential in, scrubbed and bounded output out."""

from dataclasses import dataclass
from enum import StrEnum
import re

from app.config.oauth_config import all_integrations, get_integration_by_id
from app.constants.connectors import (
    CONNECTOR_CALL_TIMEOUT_SECONDS,
    CONNECTOR_SECRET_PASSWORD_PLACEHOLDER,
    CONNECTOR_SECRET_PLACEHOLDER,
    CONNECTOR_SECRET_USER_PLACEHOLDER,
    CONNECTOR_STDERR_HEAD_BYTES,
    CONNECTOR_STDERR_TAIL_BYTES,
    CONNECTOR_STDOUT_HEAD_BYTES,
    CONNECTOR_STDOUT_TAIL_BYTES,
    MANAGED_BY_CONNECTOR,
)
from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.models.connector_models import ConnectorKind, ConnectorSpec
from app.models.integration_models import Integration
from app.models.oauth_models import OAuthIntegration
from app.services.connectors.commands import CallPlan, plan_call
from app.services.connectors.install import install_hosts
from app.services.connectors.rest_helper import (
    AUTH_HEADER_ENV,
    AUTH_QUERY_ENV,
    AUTH_TEMPLATE_ENV,
    BASE_URL_ENV,
    SECRET_ENV,
)
from app.services.connectors.runner import (
    ConnectorRunner,
    RunnerFile,
    RunOutcome,
    RunRequest,
    RunResult,
)
from app.services.connectors.scrub import scrub, secret_pattern
from app.services.connectors.selection import get_connector_runner
from app.utils.output_limiter import truncate_head_tail
from shared.py.wide_events import log

# What a CLI or API prints when the key itself is refused, as opposed to a missing permission.
_AUTH_FAILURE_RE = re.compile(
    r"\bHTTP 401\b|\b401 Unauthorized\b|\bError code: 401\b|\bstatus(_code)?[ :=]+401\b"
    r"|bad credentials|invalid (auth |access )?(api[ _-]?)?(key|token)|AuthenticationError"
    r"|invalid credentials|\bunauthorized\b|must be authenticated|token provided .{0,60}is not valid"
    r"|only supports using a secret or restricted key"
    r"|(token|key) (is |has )?(invalid|expired|been revoked|revoked)"
    r"|authentication (failed|required)|not logged in|unauthenticated|incorrect api key"
    r"|InvalidClientTokenId|security token included in the request is invalid"
    r"|invalid format for authorization header",
    re.IGNORECASE,
)


class ConnectorNotFoundError(LookupError):
    """Raised when the id names no connector this user owns or may use."""


class CallFailure(StrEnum):
    AUTH = "auth"
    INSTALL = "install"
    TIMEOUT = "timeout"
    RUNNER = "runner"
    EXIT = "exit"


@dataclass(frozen=True)
class ConnectorCallResult:
    """One call's outcome as the agent sees it: output already scrubbed and truncated."""

    outcome: RunOutcome
    is_write: bool
    exit_code: int | None
    stdout: str
    stderr: str
    failure: CallFailure | None
    output_capped: bool
    duration_ms: int


def catalog_connector_doc(integration: OAuthIntegration) -> Integration | None:
    """Project a catalog connector onto the document shape every connector path reads."""
    if integration.connector_config is None:
        return None
    return Integration(
        integration_id=integration.id,
        name=integration.name,
        description=integration.description,
        category=integration.category,
        managed_by=MANAGED_BY_CONNECTOR,
        source="platform",
        is_public=True,
        created_by=None,
        published_at=None,
        clone_count=0,
        connector_config=integration.connector_config,
        requires_auth=True,
        auth_type="bearer",
        icon_url=integration.icon_url,
        display_priority=integration.display_priority,
        is_featured=integration.is_featured,
    )


def catalog_connectors_for(provider_domain: str) -> list[OAuthIntegration]:
    """Return the catalog connectors GAIA ships for a provider's domain."""
    return [
        i
        for i in all_integrations()
        if i.connector_config is not None and i.connector_config.provider_domain == provider_domain
    ]


async def find_connector(connector_id: str) -> Integration | None:
    """Return the catalog or custom connector with this id, whoever owns it."""
    if (platform := get_integration_by_id(connector_id)) is not None:
        return catalog_connector_doc(platform)
    doc = await integration_repository.get_custom(connector_id)
    if doc is None or doc.managed_by != MANAGED_BY_CONNECTOR or doc.connector_config is None:
        return None
    return doc


async def load_connector(user_id: str, connector_id: str) -> tuple[Integration, ConnectorSpec]:
    """Return the connector and its spec when it is in the catalog, the user's own, or published."""
    doc = await find_connector(connector_id)
    if (
        doc is None
        or doc.connector_config is None
        or (doc.created_by != user_id and not doc.is_public)
    ):
        raise ConnectorNotFoundError(connector_id)
    return doc, doc.connector_config


def _secret_halves(secret: str) -> dict[str, str]:
    user, _, password = secret.partition(":")
    return {
        CONNECTOR_SECRET_USER_PLACEHOLDER: user,
        CONNECTOR_SECRET_PASSWORD_PLACEHOLDER: password,
    }


def _render_template(template: str, secret: str) -> str:
    for placeholder, half in _secret_halves(secret).items():
        template = template.replace(placeholder, half)
    return template.replace(CONNECTOR_SECRET_PLACEHOLDER, secret)


def bound_secrets(spec: ConnectorSpec, secret: str) -> list[str]:
    """Return every value of the secret a call holds: the whole key, plus each half a file takes."""
    templates = " ".join(f.template for f in spec.credential.files)
    return [secret] + [
        half for placeholder, half in _secret_halves(secret).items() if placeholder in templates
    ]


def _secret_bindings(
    spec: ConnectorSpec, secret: str
) -> tuple[dict[str, str], tuple[RunnerFile, ...]]:
    if spec.kind is ConnectorKind.REST and spec.rest is not None:
        env = {
            BASE_URL_ENV: spec.rest.base_url,
            SECRET_ENV: secret,
            AUTH_TEMPLATE_ENV: spec.rest.auth_template,
        }
        if spec.rest.auth_header is not None:
            env[AUTH_HEADER_ENV] = spec.rest.auth_header
        if spec.rest.auth_query_param is not None:
            env[AUTH_QUERY_ENV] = spec.rest.auth_query_param
        return env, ()
    env = dict.fromkeys(spec.credential.env, secret)
    files = tuple(
        RunnerFile(path=f.path, content=_render_template(f.template, secret))
        for f in spec.credential.files
    )
    return env, files


def build_run_request(spec: ConnectorSpec, plan: CallPlan, secret: str) -> RunRequest:
    """Bind the secret where the spec says and bound the call to the spec's hosts."""
    env, files = _secret_bindings(spec, secret)
    return RunRequest(
        install=tuple(spec.install),
        install_hosts=install_hosts(spec.install),
        call_hosts=tuple(spec.allowed_hosts),
        argv=plan.argv,
        timeout_seconds=CONNECTOR_CALL_TIMEOUT_SECONDS,
        env=env,
        files=files,
    )


def classify_failure(result: RunResult) -> CallFailure | None:
    """Name why a call failed, reading the key's refusal out of the output; None when it succeeded."""
    match result.outcome:
        case RunOutcome.OK:
            return None
        case RunOutcome.INSTALL_FAILED:
            return CallFailure.INSTALL
        case RunOutcome.TIMEOUT:
            return CallFailure.TIMEOUT
        case RunOutcome.RUNNER_UNAVAILABLE:
            return CallFailure.RUNNER
        case RunOutcome.EXIT_NONZERO:
            if _AUTH_FAILURE_RE.search(result.stderr) or _AUTH_FAILURE_RE.search(
                result.stdout[:CONNECTOR_STDOUT_HEAD_BYTES]
            ):
                return CallFailure.AUTH
            return CallFailure.EXIT


async def run_with_secret(
    spec: ConnectorSpec, args: list[str], secret: str, *, runner: ConnectorRunner | None = None
) -> ConnectorCallResult:
    """Run one call in a fresh runner (this deployment's, unless one is named) with the secret scrubbed out."""
    plan = plan_call(spec, args)
    chosen = runner or await get_connector_runner()
    result = await chosen.run(build_run_request(spec, plan, secret))
    pattern = secret_pattern(bound_secrets(spec, secret))
    stdout = scrub(result.stdout, pattern)
    stderr = scrub(result.stderr, pattern)
    failure = classify_failure(result)
    log.set_ns(
        "connector",
        kind=spec.kind,
        outcome=result.outcome,
        exit_code=result.exit_code,
        failure=failure,
        duration_ms=result.duration_ms,
        output_capped=result.output_capped,
        stdout_bytes=len(result.stdout),
    )
    if failure in (CallFailure.INSTALL, CallFailure.RUNNER):
        log.warning(f"{LogTag.INTEGRATION} Connector call never ran", failure=failure)
    return ConnectorCallResult(
        outcome=result.outcome,
        is_write=plan.is_write,
        exit_code=result.exit_code,
        stdout=truncate_head_tail(stdout, CONNECTOR_STDOUT_HEAD_BYTES, CONNECTOR_STDOUT_TAIL_BYTES),
        stderr=truncate_head_tail(stderr, CONNECTOR_STDERR_HEAD_BYTES, CONNECTOR_STDERR_TAIL_BYTES),
        failure=failure,
        output_capped=result.output_capped,
        duration_ms=result.duration_ms,
    )
