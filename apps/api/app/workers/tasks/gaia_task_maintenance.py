"""
GaiaTask maintenance scan — deterministic 30-minute sweep.

No LLM calls. Finds expired tasks, stalled work, and tasks waiting too long.
Sends notifications and updates statuses.
"""

from datetime import datetime, timedelta, timezone

from shared.py.wide_events import log, wide_task

from app.db.mongodb.collections import gaia_tasks_collection, proactive_runs_collection
from app.models.gaia_task_models import GaiaTaskStatus
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.gaia_task_service import gaia_task_service
from app.services.notification_service import notification_service


async def scan_gaia_tasks(ctx: dict) -> str:
    """
    Maintenance scan for GaiaTasks. Runs every 30 minutes via ARQ cron.

    Three sweeps:
    1. Expire tasks past their deadline
    2. Detect stalled ACTIVE tasks (no update in 7 days)
    3. Notify about WAITING tasks stuck for 3+ days
    """
    async with wide_task("scan_gaia_tasks"):
        now = datetime.now(timezone.utc)
        scan_start = now
        expired_count = 0
        stalled_count = 0
        waiting_notified_count = 0
        errors = 0

        # --- Sweep 1: Expire overdue tasks ---
        try:
            expired_count = await _sweep_expired_tasks(now)
        except Exception as e:
            log.error(f"Sweep 1 (expired) failed: {e}")
            errors += 1

        # --- Sweep 2: Detect stalled ACTIVE tasks ---
        try:
            stalled_count = await _sweep_stalled_tasks(now)
        except Exception as e:
            log.error(f"Sweep 2 (stalled) failed: {e}")
            errors += 1

        # --- Sweep 3: Notify about WAITING tasks ---
        try:
            waiting_notified_count = await _sweep_waiting_tasks(now)
        except Exception as e:
            log.error(f"Sweep 3 (waiting) failed: {e}")
            errors += 1

        # Record the scan run
        completed_at = datetime.now(timezone.utc)
        await proactive_runs_collection.insert_one(
            {
                "scan_type": "gaia_task_maintenance",
                "started_at": scan_start,
                "completed_at": completed_at,
                "duration_ms": int(
                    (completed_at - scan_start).total_seconds() * 1000
                ),
                "expired_count": expired_count,
                "stalled_count": stalled_count,
                "waiting_notified_count": waiting_notified_count,
                "errors": errors,
            }
        )

        log.set(
            expired_count=expired_count,
            stalled_count=stalled_count,
            waiting_notified_count=waiting_notified_count,
            errors=errors,
        )

        msg = (
            f"scan_gaia_tasks: expired={expired_count}, "
            f"stalled={stalled_count}, waiting_notified={waiting_notified_count}, "
            f"errors={errors}"
        )
        log.info(msg)
        return msg


async def _sweep_expired_tasks(now: datetime) -> int:
    """Find tasks past their expires_at deadline and expire them."""
    cursor = gaia_tasks_collection.find(
        {
            "expires_at": {"$lt": now, "$ne": None},
            "status": {
                "$nin": [
                    GaiaTaskStatus.COMPLETED,
                    GaiaTaskStatus.CANCELLED,
                    GaiaTaskStatus.EXPIRED,
                ]
            },
        }
    )
    docs = await cursor.to_list(length=100)
    count = 0

    for doc in docs:
        doc.pop("_id", None)
        try:
            await gaia_task_service.expire_task(
                task_id=doc["task_id"], user_id=doc["user_id"]
            )

            await notification_service.create_notification(
                NotificationRequest(
                    user_id=doc["user_id"],
                    source=NotificationSourceEnum.GAIA_TASK_ATTENTION,
                    type=NotificationType.WARNING,
                    content=NotificationContent(
                        title="Task Expired",
                        body=f'Your task "{doc["title"]}" has expired without completion.',
                    ),
                    channels=[
                        ChannelConfig(
                            channel_type="inapp", enabled=True, priority=2
                        )
                    ],
                    metadata={"task_id": doc["task_id"], "action": "expired"},
                )
            )
            count += 1
        except Exception as e:
            log.error(f"Failed to expire task {doc['task_id']}: {e}")

    return count


async def _sweep_stalled_tasks(now: datetime) -> int:
    """Find ACTIVE tasks with no update in 7 days and mark as STALLED."""
    stale_cutoff = now - timedelta(days=7)

    cursor = gaia_tasks_collection.find(
        {
            "status": GaiaTaskStatus.ACTIVE,
            "updated_at": {"$lt": stale_cutoff},
        }
    )
    docs = await cursor.to_list(length=100)
    count = 0

    for doc in docs:
        doc.pop("_id", None)
        try:
            await gaia_tasks_collection.update_one(
                {"task_id": doc["task_id"], "user_id": doc["user_id"]},
                {
                    "$set": {
                        "status": GaiaTaskStatus.STALLED,
                        "updated_at": now,
                    }
                },
            )

            await notification_service.create_notification(
                NotificationRequest(
                    user_id=doc["user_id"],
                    source=NotificationSourceEnum.GAIA_TASK_ATTENTION,
                    type=NotificationType.INFO,
                    content=NotificationContent(
                        title="Task Needs Attention",
                        body=f'Your task "{doc["title"]}" has had no activity for 7 days.',
                    ),
                    channels=[
                        ChannelConfig(
                            channel_type="inapp", enabled=True, priority=3
                        )
                    ],
                    metadata={"task_id": doc["task_id"], "action": "stalled"},
                )
            )
            count += 1
        except Exception as e:
            log.error(f"Failed to stall task {doc['task_id']}: {e}")

    return count


async def _sweep_waiting_tasks(now: datetime) -> int:
    """Find WAITING tasks with no update in 3 days and notify user."""
    waiting_cutoff = now - timedelta(days=3)

    cursor = gaia_tasks_collection.find(
        {
            "status": GaiaTaskStatus.WAITING,
            "updated_at": {"$lt": waiting_cutoff},
        }
    )
    docs = await cursor.to_list(length=100)
    count = 0

    for doc in docs:
        doc.pop("_id", None)
        try:
            days_waiting = (now - doc["updated_at"]).days

            await notification_service.create_notification(
                NotificationRequest(
                    user_id=doc["user_id"],
                    source=NotificationSourceEnum.GAIA_TASK_ATTENTION,
                    type=NotificationType.INFO,
                    content=NotificationContent(
                        title="Still Waiting",
                        body=(
                            f'Your task "{doc["title"]}" has been waiting '
                            f"for {days_waiting} days with no response."
                        ),
                    ),
                    channels=[
                        ChannelConfig(
                            channel_type="inapp", enabled=True, priority=3
                        )
                    ],
                    metadata={
                        "task_id": doc["task_id"],
                        "action": "waiting_reminder",
                    },
                )
            )
            count += 1
        except Exception as e:
            log.error(f"Failed to notify waiting task {doc['task_id']}: {e}")

    return count
