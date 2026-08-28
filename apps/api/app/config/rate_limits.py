"""
Rate limiting configuration for all features.
Single source of truth for rate limits.

Rate limits are enforced across two time periods:
- Daily: Medium-term usage control
- Monthly: Long-term subscription limits

Both limits are checked on each request. If any limit is exceeded,
the request is rejected with a 429 status code.

Usage:
    @tiered_rate_limit("generate_image")
    async def generate_image(user: dict = Depends(get_current_user)):
        # This endpoint will be limited by daily (50/1000) and monthly (1000/25000)
        # limits based on user's plan
        pass
"""

from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import BaseModel

from app.constants.llm import (
    FREE_DAILY_COST_BUDGET_USD,
    FREE_PER_REQUEST_TOKEN_CEILING,
    PRO_DAILY_COST_BUDGET_USD,
    PRO_PER_REQUEST_TOKEN_CEILING,
)
from app.models.payment_models import PlanType


class RateLimitPeriod(str, Enum):
    """Time window a limit applies to."""

    DAY = "day"
    MONTH = "month"


class RateLimitConfig(BaseModel):
    """Allowed request counts per day and per month (0 = no limit for that period)."""

    day: int = 0
    month: int = 0


class FeatureInfo(BaseModel):
    """User-facing title and description for a rate-limited feature."""

    title: str
    description: str


class TieredRateLimits(BaseModel):
    """Per-plan rate limit configs for one feature."""

    free: RateLimitConfig = RateLimitConfig()
    pro: RateLimitConfig = RateLimitConfig()
    info: FeatureInfo
    # Whether a successful call is a deliberate user action that shows on the
    # activity heatmap. False for infra/polling endpoints (artifact fetches,
    # agent file reads, system notifications) that would otherwise drown it out
    # and distort the cross-user percentile thresholds.
    counts_as_activity: bool = True


# RECOMMENDED FEATURE LIMITS FOR $30/MONTH
FEATURE_LIMITS: dict[str, TieredRateLimits] = {
    # CORE COMMUNICATION
    "chat_messages": TieredRateLimits(
        # Free has NO daily message count either: the rolling daily COST budget
        # (FREE_DAILY_COST_BUDGET_USD) is the real wall, so a message tally
        # would just double-wall the same thing less honestly. The monthly count
        # stays only as an extreme abuse backstop a human can't reach before the
        # cost wall stops them (day=0 = counted but not enforced, so day-by-day
        # usage charts still get data).
        free=RateLimitConfig(day=0, month=2000),  # TUNE — abuse backstop, not a wall
        # Pro has NO daily message count: usage is priced by the cost budgets
        # (daily abuse guard + monthly economic guard), not by counting
        # messages. The monthly count stays only as an extreme abuse backstop
        # a human can never hit.
        pro=RateLimitConfig(day=0, month=60000),
        info=FeatureInfo(title="Chat Messages", description="Send messages to AI assistants"),
    ),
    # VOICE (Very Expensive - LiveKit + STT + TTS per session)
    "voice_mode": TieredRateLimits(
        free=RateLimitConfig(day=0, month=0),  # Paid-only: no free usage
        # Counted per /token mint (session start), so heavy daily use plus
        # reconnects must fit comfortably.
        pro=RateLimitConfig(day=200, month=6000),  # month = day x30
        info=FeatureInfo(
            title="Voice Mode",
            description="Real-time voice conversations with GAIA",
        ),
    ),
    # FILE OPERATIONS (Expensive - Storage & Processing)
    "file_upload": TieredRateLimits(
        free=RateLimitConfig(day=2, month=5),  # Keep restrictive
        pro=RateLimitConfig(day=150, month=4500),  # +50%
        info=FeatureInfo(title="File Upload", description="Upload and process files"),
    ),
    "file_analysis": TieredRateLimits(
        free=RateLimitConfig(day=3, month=10),  # Keep restrictive
        pro=RateLimitConfig(day=150, month=4500),  # +50%
        info=FeatureInfo(title="File Analysis", description="Analyze and process uploaded files"),
    ),
    "audio_transcription": TieredRateLimits(
        free=RateLimitConfig(day=5, month=20),
        pro=RateLimitConfig(day=200, month=6000),
        info=FeatureInfo(
            title="Audio Transcription",
            description="Transcribe voice notes and audio clips to text",
        ),
    ),
    "session_files": TieredRateLimits(
        # Static-ish artifact fetches + tab-focus reconcile polling — generous.
        free=RateLimitConfig(day=5000, month=100000),
        pro=RateLimitConfig(day=50000, month=1000000),
        info=FeatureInfo(
            title="Session Files",
            description="Fetch workspace artifacts and uploaded files",
        ),
        counts_as_activity=False,  # polling, not a user action
    ),
    # SKILLS
    "skill_operations": TieredRateLimits(
        free=RateLimitConfig(day=5, month=20),
        pro=RateLimitConfig(day=150, month=4500),
        info=FeatureInfo(
            title="Skill Operations",
            description="Install, create, and manage agent skills",
        ),
    ),
    # AI GENERATION (Very Expensive)
    "generate_image": TieredRateLimits(
        free=RateLimitConfig(day=1, month=2),  # Keep very restrictive
        pro=RateLimitConfig(day=45, month=1350),  # +50% (30→45, 900→1350)
        info=FeatureInfo(
            title="AI Image Generation", description="Generate images using AI models"
        ),
    ),
    "deep_research": TieredRateLimits(
        # Heaviest tool: one call fans out to many searches and page fetches.
        free=RateLimitConfig(day=1, month=5),  # TUNE — a taste, not a workload
        # Monthly is intentionally below day x30 (would be 3000): this is the most
        # expensive tool, so the month acts as an economic guard, not a x30 mirror.
        pro=RateLimitConfig(day=100, month=2000),
        info=FeatureInfo(
            title="Deep Research",
            description="Multi-source parallel research with full content analysis and synthesis",
        ),
    ),
    "document_generation": TieredRateLimits(
        free=RateLimitConfig(day=1, month=3),  # Keep restrictive
        pro=RateLimitConfig(day=45, month=1350),  # +50% (30→45, 900→1350)
        info=FeatureInfo(title="Document Generation", description="Generate documents and reports"),
    ),
    # WEB FEATURES (Moderate Cost)
    "web_search": TieredRateLimits(
        # Search itself is cheap (Exa free tier + self-hosted fallback), but
        # every result feeds LLM context and 100/day invites scripted scraping
        # through the agent.
        free=RateLimitConfig(day=20, month=150),  # TUNE
        # Monthly is intentionally below day x30 (would be 150000): every result
        # feeds LLM context, so the month caps context-cost abuse, not a x30 mirror.
        pro=RateLimitConfig(day=5000, month=50000),
        info=FeatureInfo(title="Web Search", description="Search the web for information"),
    ),
    "webpage_fetch": TieredRateLimits(
        free=RateLimitConfig(day=3, month=10),  # Keep restrictive
        pro=RateLimitConfig(day=150, month=4500),  # +50% (100→150, 3000→4500)
        info=FeatureInfo(title="Webpage Fetch", description="Fetch and analyze web pages"),
    ),
    "download": TieredRateLimits(
        free=RateLimitConfig(day=20, month=200),
        pro=RateLimitConfig(day=300, month=9000),
        info=FeatureInfo(
            title="File Download", description="Download a file from a URL into the workspace"
        ),
    ),
    # AUTOMATION (High Value)
    "workflow_operations": TieredRateLimits(
        free=RateLimitConfig(day=5, month=20),  # Keep restrictive
        pro=RateLimitConfig(day=45, month=1350),  # +50% (30→45, 900→1350)
        info=FeatureInfo(
            title="Workflow Operations",
            description="Create, execute, and manage AI workflows",
        ),
    ),
    "trigger_workflow_executions": TieredRateLimits(
        free=RateLimitConfig(day=5, month=20),  # Keep restrictive (trial)
        # Account-level triggers (e.g. Gmail) fire one execution per event, so Pro
        # needs real headroom; the cap stays as a cost guard, not a daily blocker.
        pro=RateLimitConfig(day=1500, month=45000),
        info=FeatureInfo(
            title="Trigger Workflow Executions",
            description="Automated workflow executions triggered by integrations",
        ),
        # System-driven fires, not user actions: counting them let a user's own
        # automation keep them "active" forever (masking dormancy) and inflated
        # the activity heatmap / percentile badges with runs nobody performed.
        counts_as_activity=False,
    ),
    # PRODUCTIVITY TOOLS (Generous - Core Value)
    "todo_operations": TieredRateLimits(
        free=RateLimitConfig(day=50, month=1000),  # Good trial experience
        pro=RateLimitConfig(day=1500, month=45000),  # month = day x30
        info=FeatureInfo(
            title="Todo Operations", description="Create, update, and manage todo items"
        ),
    ),
    "calendar_management": TieredRateLimits(
        free=RateLimitConfig(day=5, month=50),  # Keep restrictive for trial
        pro=RateLimitConfig(day=1500, month=45000),  # month = day x30
        info=FeatureInfo(
            title="Calendar Management",
            description="Create, update, and manage calendar events",
        ),
    ),
    "reminder_operations": TieredRateLimits(
        free=RateLimitConfig(day=3, month=10),  # Keep restrictive
        pro=RateLimitConfig(day=150, month=4500),  # +50% (100→150, 3000→4500)
        info=FeatureInfo(title="Reminder Operations", description="Create and manage reminders"),
    ),
    # COMMUNICATION
    "mail_actions": TieredRateLimits(
        free=RateLimitConfig(day=2, month=5),  # Keep very restrictive
        pro=RateLimitConfig(day=75, month=2250),  # +50% (50→75, 1500→2250)
        info=FeatureInfo(
            title="Mail Actions", description="Send emails and manage mail operations"
        ),
    ),
    # KNOWLEDGE MANAGEMENT
    "notes": TieredRateLimits(
        free=RateLimitConfig(day=30, month=200),  # Good trial
        pro=RateLimitConfig(day=1500, month=45000),  # +50% (1000→1500, 30000→45000)
        info=FeatureInfo(title="Notes Management", description="Create and manage notes"),
    ),
    "memory": TieredRateLimits(
        free=RateLimitConfig(day=20, month=100),  # Good trial
        pro=RateLimitConfig(day=750, month=22500),  # +50% (500→750, 15000→22500)
        info=FeatureInfo(title="Memory Operations", description="Store and retrieve memories"),
    ),
    # Coding tools (persistent E2B workspace)
    "sandbox_creation": TieredRateLimits(
        # Each create provisions a fresh E2B VM — real infra cost the LLM cost
        # budget cannot see, so the count is the only guard here.
        free=RateLimitConfig(day=1, month=5),  # TUNE
        pro=RateLimitConfig(day=150, month=4500),  # month = day x30
        info=FeatureInfo(
            title="Sandbox Creation",
            description="Provision a fresh coding sandbox for shell and workspace tools",
        ),
    ),
    "bash_execution": TieredRateLimits(
        # Sandbox compute time — invisible to the token budget.
        free=RateLimitConfig(day=10, month=100),  # TUNE
        pro=RateLimitConfig(day=1500, month=45000),
        info=FeatureInfo(
            title="Shell Execution",
            description="Run shell commands in the persistent coding sandbox",
        ),
    ),
    "workspace_read": TieredRateLimits(
        free=RateLimitConfig(day=500, month=15000),
        pro=RateLimitConfig(day=20000, month=600000),
        info=FeatureInfo(
            title="Workspace Read",
            description="Read files from the persistent coding workspace",
        ),
        counts_as_activity=False,  # high-frequency agent reads, not a user action
    ),
    "workspace_write": TieredRateLimits(
        free=RateLimitConfig(day=50, month=1000),  # TUNE — trial use, not automation
        pro=RateLimitConfig(day=5000, month=150000),
        info=FeatureInfo(
            title="Workspace Write",
            description="Write files to the persistent coding workspace",
        ),
    ),
    "workspace_edit": TieredRateLimits(
        free=RateLimitConfig(day=50, month=1000),  # TUNE — trial use, not automation
        pro=RateLimitConfig(day=5000, month=150000),
        info=FeatureInfo(
            title="Workspace Edit",
            description="Edit files in the persistent coding workspace",
        ),
    ),
    # Read-only miners over offloaded workspace files (mirror workspace_read's
    # generous limits — a large-inbox triage fans these out across chunks).
    "workspace_query_json": TieredRateLimits(
        free=RateLimitConfig(day=500, month=15000),
        pro=RateLimitConfig(day=20000, month=600000),
        info=FeatureInfo(
            title="Workspace Query",
            description="Filter/aggregate offloaded JSON/JSONL files in the coding workspace",
        ),
    ),
    "workspace_grep": TieredRateLimits(
        free=RateLimitConfig(day=500, month=15000),
        pro=RateLimitConfig(day=20000, month=600000),
        info=FeatureInfo(
            title="Workspace Grep",
            description="Search files in the persistent coding workspace",
        ),
    ),
    # CREATIVE TOOLS
    "flowchart_creation": TieredRateLimits(
        free=RateLimitConfig(day=1, month=3),  # Keep restrictive
        pro=RateLimitConfig(day=30, month=900),  # +50% (20→30, 600→900)
        info=FeatureInfo(title="Flowchart Creation", description="Create flowcharts and diagrams"),
    ),
    # UTILITY
    "weather_checks": TieredRateLimits(
        free=RateLimitConfig(day=5, month=20),  # Unchanged
        pro=RateLimitConfig(day=150, month=4500),  # +50% (100→150, 3000→4500)
        info=FeatureInfo(title="Weather Checks", description="Check weather information"),
    ),
    "notification_operations": TieredRateLimits(
        free=RateLimitConfig(day=50, month=1000),  # Reduced from 100/2000 (too generous)
        pro=RateLimitConfig(day=7500, month=225000),  # +50% (5000→7500, 150000→225000)
        info=FeatureInfo(title="Notification Operations", description="Manage user notifications"),
        counts_as_activity=False,  # system-driven, not a user action
    ),
    # MARKETPLACE (Community)
    "integration_publish": TieredRateLimits(
        # Community engagement — near-frictionless on both tiers (low cost, high value).
        free=RateLimitConfig(day=50, month=1500),
        pro=RateLimitConfig(day=1500, month=45000),  # month = day x30
        info=FeatureInfo(
            title="Integration Publishing",
            description="Publish custom integrations to the community marketplace",
        ),
    ),
    "integration_clone": TieredRateLimits(
        # Cloning is the common path — keep it wide open on both tiers.
        free=RateLimitConfig(day=100, month=3000),
        pro=RateLimitConfig(day=3000, month=90000),  # month = day x30
        info=FeatureInfo(
            title="Integration Cloning",
            description="Clone community integrations to your workspace",
        ),
    ),
    "imessage_registration": TieredRateLimits(
        # Abuse guard: each connect burns a seat in Photon's shared pool. Free is zeroed (Pro-only).
        free=RateLimitConfig(day=0, month=0),
        pro=RateLimitConfig(day=10, month=100),
        info=FeatureInfo(
            title="iMessage Registration",
            description="Register a phone number on the GAIA iMessage pool",
        ),
    ),
    "account_platform_connect": TieredRateLimits(
        # Abuse guard: minting link credentials from chat. Conservative —
        # connecting a platform is rare; even 5/day is far above real use.
        free=RateLimitConfig(day=5, month=25),
        pro=RateLimitConfig(day=10, month=50),
        info=FeatureInfo(
            title="Platform Connect",
            description="Generate platform connection links from chat",
        ),
    ),
}


# The feature whose usage windows the usage UI leads with. Chat is the metered
# surface every plan revolves around (its free wall is the daily cost budget),
# so the dashboard headlines it. Single source of truth shared with the client.
PRIMARY_METERED_FEATURE = "chat_messages"


def get_feature_limits(feature_key: str) -> TieredRateLimits:
    """Get rate limits for a specific feature."""
    if feature_key not in FEATURE_LIMITS:
        raise ValueError(f"Unknown feature key: {feature_key}")
    return FEATURE_LIMITS[feature_key]


def get_limits_for_plan(feature_key: str, plan_type: PlanType) -> RateLimitConfig:
    """Get rate limits for a specific feature and plan."""
    limits = get_feature_limits(feature_key)
    # Dispatch on PRO, not "not FREE": an unrecognized plan should fall back to
    # the restrictive tier, never silently receive the paid allowance.
    return limits.pro if plan_type == PlanType.PRO else limits.free


def get_reset_time(period: RateLimitPeriod) -> datetime:
    """Calculate reset time for a given period."""
    now = datetime.now(UTC)
    if period == RateLimitPeriod.DAY:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    # MONTH
    if now.month == 12:
        return now.replace(
            year=now.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def get_time_window_key(period: RateLimitPeriod) -> str:
    """Get Redis time window key for a period."""
    now = datetime.now(UTC)
    if period == RateLimitPeriod.DAY:
        return now.strftime("%Y%m%d")
    # MONTH
    return now.strftime("%Y%m")


def get_per_request_token_ceiling(plan_type: PlanType) -> int:
    """Aggregate token ceiling for a single request, by plan."""
    return (
        FREE_PER_REQUEST_TOKEN_CEILING
        if plan_type == PlanType.FREE
        else PRO_PER_REQUEST_TOKEN_CEILING
    )


def get_daily_cost_budget_usd(plan_type: PlanType) -> float:
    """Rolling daily USD cost budget, by plan. Free = usage wall, pro = abuse guard."""
    return FREE_DAILY_COST_BUDGET_USD if plan_type == PlanType.FREE else PRO_DAILY_COST_BUDGET_USD


def get_feature_info(feature_key: str) -> FeatureInfo:
    """Get user-friendly feature information."""
    if feature_key in FEATURE_LIMITS:
        return FEATURE_LIMITS[feature_key].info
    return FeatureInfo(
        title=feature_key.replace("_", " ").title(),
        description=f"Usage for {feature_key}",
    )


def _is_cost_walled(limits: TieredRateLimits) -> bool:
    """A feature whose daily use is gated by the rolling cost budget, not a
    message count: day == 0 on BOTH tiers (so the count never caps daily use)
    while free still has monthly access. Chat is the canonical case — its free
    wall is FREE_DAILY_COST_BUDGET_USD, not a per-day message tally.
    """
    return limits.free.day == 0 and limits.pro.day == 0 and limits.free.month > 0


def _free_pro_delta(feature_key: str) -> dict[str, str] | None:
    """One upsell bullet comparing free vs pro for a feature, or None.

    A pro limit of 0 means that period is uncapped on Pro, which is the
    strongest possible pitch.
    """
    limits = FEATURE_LIMITS[feature_key]
    # Cost-walled feature (chat): daily use is capped by the rolling cost budget,
    # never a message count, so the pitch stays qualitative and count-free.
    # Naming a per-month number ("60,000 instead of 2,000") would be dishonest
    # (the month is only an abuse backstop, not the wall a user feels) and
    # off-strategy — Pro's real chat win is far more daily AI usage.
    if _is_cost_walled(limits):
        return {"title": limits.info.title, "detail": "unlimited daily messages"}
    if limits.free.day > 0:
        if limits.pro.day > 0:
            detail = f"{limits.pro.day:,} per day instead of {limits.free.day:,}"
        else:
            # Pro uncaps daily use while free stays count-bounded: stay
            # qualitative and never name the free daily count.
            detail = "unlimited daily use"
        return {"title": limits.info.title, "detail": detail}
    if limits.free.month > 0 and limits.pro.month > 0:
        return {
            "title": limits.info.title,
            "detail": f"{limits.pro.month:,} per month instead of {limits.free.month:,}",
        }
    return None


def derive_pro_benefits(hit_feature: str, max_other: int = 3) -> list[dict[str, str]]:
    """Build upsell bullets from FEATURE_LIMITS — the same config that enforces
    the limits, so the promised benefits can never drift from reality.

    Order: (1) the feature the user just hit, (2) Pro-only features (no free
    access at all), (3) features whose daily use is not count-capped on Pro —
    either free-capped daily with no pro cap, or cost-walled (day 0 on both
    tiers, e.g. chat messages), (4) the largest free->pro daily multipliers.
    """
    benefits: list[dict[str, str]] = []
    seen: set[str] = set()

    if hit_feature in FEATURE_LIMITS:
        delta = _free_pro_delta(hit_feature)
        if delta:
            benefits.append(delta)
            seen.add(hit_feature)

    for key, limits in FEATURE_LIMITS.items():
        if key in seen:
            continue
        free_gated = limits.free.day <= 0 and limits.free.month <= 0
        pro_has_access = limits.pro.day > 0 or limits.pro.month > 0
        if free_gated and pro_has_access:
            benefits.append({"title": limits.info.title, "detail": "included with Pro"})
            seen.add(key)

    # Features whose daily use is uncapped on Pro (pro.day == 0) are the
    # strongest non-gated pitch, but the multiplier section below can't reach
    # them (division by pro.day). This covers both free-capped-daily features
    # and cost-walled ones (chat: day 0 on both tiers). Surface them explicitly
    # so a wall on any feature still advertises e.g. unlimited chat messages.
    for key, limits in FEATURE_LIMITS.items():
        if key in seen:
            continue
        if limits.pro.day <= 0 and (limits.free.day > 0 or _is_cost_walled(limits)):
            delta = _free_pro_delta(key)
            if delta:
                benefits.append(delta)
                seen.add(key)

    multipliers = sorted(
        (
            (limits.pro.day / limits.free.day, key)
            for key, limits in FEATURE_LIMITS.items()
            if key not in seen and limits.free.day > 0 and limits.pro.day > 0
        ),
        reverse=True,
    )
    for _, key in multipliers[:max_other]:
        delta = _free_pro_delta(key)
        if delta:
            benefits.append(delta)

    return benefits
