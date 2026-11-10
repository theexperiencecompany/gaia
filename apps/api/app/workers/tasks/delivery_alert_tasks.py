"""ARQ tasks that turn reported delivery failures into Slack incidents."""

from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.alerting import alert_delivery_failure, refresh_delivery_incident
from app.workers.task_envelope import ArqJobContext


async def record_delivery_failure(_ctx: ArqJobContext, failure_json: str) -> str:
    """Add one reported failure to its incident and post what is due in Slack."""
    parsed = DeliveryFailure.model_validate_json(failure_json)
    await alert_delivery_failure(parsed)
    return f"record_delivery_failure {parsed.platform.value}:{parsed.kind.value}"


async def refresh_delivery_incident_task(_ctx: ArqJobContext, fingerprint: str) -> str:
    """Bring an incident's parent Slack message up to date."""
    await refresh_delivery_incident(fingerprint)
    return f"refresh_delivery_incident {fingerprint}"
