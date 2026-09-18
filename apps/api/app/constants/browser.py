"""Constants for the Browser-Use browser-automation capability.

Single source of truth for the tool name, the SSE card-event keys, the Redis
handoff namespace, and the heuristics that decide when the browser agent must
hand control to the human. Values a deployment may tune live in settings;
values that are part of the wire/UI contract live here so backend and frontend
cannot drift.

The startup gate ("do you want me to use a browser?") is handled by the shared
HIL system (browser_task is registered destructive). This module governs the
mid-run gate: when the agent reaches a payment, credential, or irreversible
step, a per-task policy decides whether to hand off to the user (live-view),
proceed autonomously (e.g. a configured agent card), or abort.
"""

from enum import Enum, StrEnum

# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------
BROWSER_TOOL_NAME = "browser_task"
BROWSER_TOOL_CATEGORY = "browser"


class BrowserEngine(StrEnum):
    """Which browser binary gaia-browser-host launches behind its CDP plane.

    CHROMIUM is the default headless-shell path. OBSCURA runs the Obscura CDP
    server beside it, a drop-in over the same CDP, selected by BROWSER_ENGINE."""

    CHROMIUM = "chromium"
    OBSCURA = "obscura"


# ---------------------------------------------------------------------------
# SSE card-event key (must match tool_fields in chat_models.py and the frontend TOOL_RENDERERS/toolRegistry registration).
# ---------------------------------------------------------------------------
BROWSER_TASK_EVENT = "browser_task_data"


class BrowserEventKind(str, Enum):
    """Discriminator for a single browser_task_data snapshot entry."""

    SESSION = "session"
    STEP = "step"
    HANDOFF = "handoff"
    RESULT = "result"


class BrowserSessionStatus(str, Enum):
    """Lifecycle state of a browser session: created to live/working to ended/failed."""

    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SensitiveCategory(str, Enum):
    """Why a planned browser step is sensitive."""

    NONE = "none"
    PAYMENT = "payment"
    CREDENTIALS = "credentials"
    IRREVERSIBLE = "irreversible"


# Shown on a CREDENTIALS handoff: the session is saved (Fernet-encrypted per
# user+site) and reused so the next task skips the login. Kept truthful to
# storage_persistence.py; the Browser settings page can list/remove saved sites.
BROWSER_CREDENTIALS_SAVED_NOTE = (
    "Once you're signed in, I'll save this site's session, encrypted, so I can "
    "skip the login next time. You can remove saved sites anytime in "
    "your Browser settings."
)


class HandoffStatus(str, Enum):
    """State of a live-view handoff: pending, completed, cancelled, expired."""

    PENDING = "pending"
    COMPLETED = "completed"  # user finished the step in live-view → resume
    CANCELLED = "cancelled"  # user cancelled → abort
    TIMEOUT = "timeout"  # nobody acted → abort


class HandoffDecision(str, Enum):
    """User decision on a pending handoff, or a note-only reply."""

    CONTINUE = "continue"
    CANCEL = "cancel"


class BrowserLoginSource(StrEnum):
    """Where a saved login came from.

    Absent for logins acquired by browsing; stamped on the per-host docs the
    gaia connect CLI import writes."""

    IMPORT = "import"


# Defined here rather than beside JevOperation because BROWSER_TAKEOVER_PREAMBLE
# below interpolates it at import time.
class BrowserHandoffAction(StrEnum):
    """The two actions GAIA registers with Browser-Use to hand a step to the human."""

    REQUEST_HUMAN_TAKEOVER = "request_human_takeover"
    SOLVE_CAPTCHA_WITH_HELP = "solve_captcha_with_help"


# --- Redis handoff bridge ---
# Browser-session continue/cancel signal only, not tool-call approval
# (the shared HIL system owns that).
BROWSER_HANDOFF_KEY_PREFIX = "browser:handoff:"
# Maps a conversation to its one in-flight handoff id, so a plain chat reply
# ("yeah I paid, continue") can resolve it — the text-channel equivalent of the
# card's Continue/Cancel buttons. Both surfaces converge on ``resolve_handoff``.
BROWSER_HANDOFF_CONV_KEY_PREFIX = "browser:handoff:conv:"
HANDOFF_POLL_INTERVAL_SECONDS = 1.0

# Auto-resolve a login handoff when the page navigates off the sign-in URL, so
# a visible sign-in success spares the user the "I'm done" tap. Best-effort,
# the manual resolution always races it; debounced so a transient redirect doesn't fire it early.
HANDOFF_AUTORESOLVE_POLL_SECONDS = 2.0
HANDOFF_AUTORESOLVE_STABLE_POLLS = 2
HANDOFF_KEY_TTL_SECONDS = 3600
# How often the paused run touches the host session so the idle reaper (default
# 300s TTL) never disposes a browser the user was asked to come back to.
BROWSER_HANDOFF_KEEPALIVE_SECONDS = 60

# A short capability code for the bot's live-view link (browser.heygaia.io/{code}):
# the code IS the secret and maps to the session + owner in Redis, so the link
# carries no 32-char session id and no long ?t= token. TTL bounds the link's life.
BROWSER_LIVE_CODE_KEY_PREFIX = "browser:livecode:"
BROWSER_LIVE_CODE_TTL_SECONDS = 3600

# Replay: a short code maps to a finished session's screenshot set, so the recap
# link (browser.heygaia.io/replays/{code}) plays every step back as a slideshow.
# Longer-lived than the live code — a recap should still open days later.
BROWSER_REPLAY_CODE_KEY_PREFIX = "browser:replay:"
BROWSER_REPLAY_CODE_TTL_SECONDS = 7 * 24 * 3600
# Bytes of entropy for the code (token_urlsafe → ~1.3 chars/byte, so ~12 chars).
BROWSER_LIVE_CODE_ENTROPY_BYTES = 9

# Step frames kept on local disk when no object store is configured, served back
# through a code of their own so the frames are not enumerable by session id.
# One code per run: code -> run, and run -> code so every step reuses it.
BROWSER_SHOT_CODE_KEY_PREFIX = "browser:shotcode:"
BROWSER_SHOT_SESSION_KEY_PREFIX = "browser:shotsess:"

# Session-import handoff: a short-lived, single-use code minted for a signed-in
# web user that the local gaia connect CLI presents to upload the extracted
# browser profile. Short TTL: redeemed within seconds; single-use: authorises writing the user's whole login state.
BROWSER_IMPORT_TOKEN_KEY_PREFIX = "browser:import:"  # nosec B105 -- Redis key prefix, not a credential
BROWSER_IMPORT_TOKEN_TTL_SECONDS = 600
BROWSER_IMPORT_TOKEN_ENTROPY_BYTES = 32

# Saved-site session data (browser_profiles) auto-expires this long after last use.
# A Mongo TTL index on ``updated_at`` reclaims it; every use refreshes the clock.
BROWSER_PROFILE_TTL_DAYS = 90
BROWSER_PROFILE_TTL_SECONDS = BROWSER_PROFILE_TTL_DAYS * 24 * 3600

# Prefixes the summary of a run that died on an unexpected error. The runner writes
# it; bot delivery strips it back off to show the user the reason alone.
BROWSER_TASK_FAILED_PREFIX = "Browser task failed: "

# Chat acks when a handoff is resolved by a natural-language reply.
BROWSER_HANDOFF_ACK_CONTINUE = "Got it, continuing the browser task."
BROWSER_HANDOFF_ACK_CANCEL = "Okay, I've stopped the browser task."

# The run's own summary when nobody finished the step in the live browser: a
# handoff that expired is a failed run, not the completed one an earlier
# takeover made it look like.
BROWSER_RUN_HANDOFF_TIMED_OUT = "Stopped: nobody finished the step in the live browser in time."

# Upper bound on how many times one task may hand off to the human, so a
# misbehaving agent can't loop the user forever.
MAX_HANDOFFS_PER_TASK = 5

# Appended to every browser task so the agent uses the takeover action instead
# of doing sensitive steps itself.
BROWSER_TAKEOVER_PREAMBLE = (
    "\n\nIMPORTANT: For any payment, login/password/OTP/2FA, or irreversible or "
    "legally-binding confirmation, do NOT do it yourself. Call the "
    f"`{BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER}` action first so the user completes that step in the "
    "live browser, then continue toward the goal.\n"
    "If you encounter a CAPTCHA, reCAPTCHA, hCaptcha, or an 'I'm not a robot' / "
    "image-grid challenge, do NOT attempt to solve it yourself. Call the "
    f"`{BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP}` action immediately on the FIRST challenge so the user "
    "solves it in the live browser, then continue. Never keep clicking challenge tiles.\n"
    # The human's part of a login should be only the secret part. Filling the
    # username yourself first means they open the live view to just a password.
    "Before you hand off a login, first fill every NON-secret field you can "
    "yourself: username, email, the account identifier, so the takeover leaves "
    "the user only the secret step (password, OTP, 2FA). Then hand off.\n"
    # Measured on a real investor-application form: given only a name and email,
    # the agent invented a phone number and country and reported the form as
    # correctly filled, fabricated data submitted under the user's name.
    "NEVER invent a value for a field the task did not give you. No made-up phone "
    "numbers, addresses, dates, amounts, countries or company details, and no "
    "plausible-looking placeholder. If a field you cannot leave empty has no value "
    f"in the task, call `{BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER}` and say which field is missing. "
    "The one exception is when the task itself says the run is a test or that dummy "
    "values are fine. Reporting a field as filled with a value you invented is a "
    "failure, not a completion.\n"
    # Measured on an Airtable form: three custom React dropdowns cost the agent
    # four steps each by clicking them open and picking by eye, while the native
    # actions read the option list and select in one step — it called them once.
    "For any dropdown, select, combobox or multiple-choice control, call "
    "`dropdown_options` to read the choices and `select_dropdown` to pick one. Do "
    "not open it by clicking and choose by sight. That takes several steps and "
    "mis-selects."
)

# Desktop viewport (the ~800x600 CDP default collapses sites to mobile layout). The live
# view caps its stream at this same size (screencast.py imports it): wider only buys a
# downscaled stream, a takeover coordinate mismatch and bigger vision payloads.
BROWSER_VIEWPORT_WIDTH = 1280
BROWSER_VIEWPORT_HEIGHT = 800


# --- Jev decision policy ---
# The operation vocabulary browser-use/jev-ultrafast offers Jev, each mapping
# onto one Browser-Use action, plus the two human-takeover controls registered here.
class JevOperation(StrEnum):
    """One Jev choice per step; the element-bound ones also carry a target index."""

    CLICK = "CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    SELECT = "SELECT"
    SCROLL_UP = "SCROLL_UP"
    SCROLL_DOWN = "SCROLL_DOWN"
    WAIT = "WAIT"
    NAVIGATE = "NAVIGATE"
    GO_BACK = "GO_BACK"
    REQUEST_HUMAN = "REQUEST_HUMAN"
    SOLVE_CAPTCHA = "SOLVE_CAPTCHA"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


# Operations that need an observed element; each gets its own speculative
# target question in the same Jev request (see services/browser/jev/policy.py).
JEV_TARGET_OPERATIONS = (JevOperation.CLICK, JevOperation.TYPE_TEXT, JevOperation.SELECT)

# Jev sees the viewport only; this bounds one screen. Measured on Wikipedia:
# 200 rows is 64,483 bytes, the gateway 400s max_tokens_exceeded from 86,133
# bytes up, and refuses a question with over 255 choices.
JEV_MAX_ELEMENTS = 200

JEV_GATEWAY_TIMEOUT_SECONDS = 25.0
JEV_GATEWAY_MAX_ATTEMPTS = 3

# Observation budget: visible page text sent as Jev state, and how much of the
# run's own action history rides along as context.
JEV_PAGE_TEXT_MAX_CHARS = 6000
JEV_ELEMENT_LABEL_MAX_CHARS = 120
JEV_RECENT_ACTIONS = 10
JEV_TEXT_HELPER_RECENT_ACTIONS = 6
JEV_TEXT_VALUE_MAX_CHARS = 2000
# Probability mass across a choice question must sum to ~1; the gateway rounds.
JEV_PROBABILITY_SUM_TOLERANCE = 0.02


# ---------------------------------------------------------------------------
# Background browser job
# ---------------------------------------------------------------------------

# One browser task per conversation; the value is the job id so a refused second
# task can name the run the user is already watching. A heartbeat lease, not a
# fixed TTL: a run may sit 30 minutes in a handoff, a dead worker must not.
BROWSER_JOB_LOCK_PREFIX = "browser:job:lock:"
BROWSER_JOB_LOCK_TTL_SECONDS = 120
BROWSER_JOB_HEARTBEAT_SECONDS = 30

# The job's durable state: what the joiner reads and what a restarted API needs
# to answer "is it still running?". Outlives the turn.
BROWSER_JOB_STATE_PREFIX = "browser:job:"
BROWSER_JOB_TTL_SECONDS = 7200

# Replayable card feed, one Redis stream per job. The relay XREADs it from 0-0,
# so a relay started late (or restarted) still shows every card from step 1.
BROWSER_JOB_EVENTS_PREFIX = "browser:job:events:"
BROWSER_JOB_EVENTS_MAXLEN = 2000

# A live executor holding this lease owns speaking the result; the worker skips
# its own delivery while it is held. Refreshed by the joiner, so an API crash
# releases it within one TTL and the worker delivers instead.
BROWSER_JOB_JOINER_PREFIX = "browser:job:joiner:"
BROWSER_JOB_JOINER_LEASE_SECONDS = 15
BROWSER_JOB_JOINER_REFRESH_SECONDS = 5

# Set by cancel_executor for a job whose turn has already ended, when the
# stream's cancel signal is gone. OR-ed with stream_manager.is_cancelled.
BROWSER_JOB_CANCEL_PREFIX = "browser:job:cancel:"

BROWSER_JOB_POLL_INTERVAL_SECONDS = 0.5

# How long the relay's read parks on an empty feed before looking at the turn
# again. Long enough that an idle run costs one read a second, short enough that
# a cancelled turn stops relaying about as fast as the user expects.
BROWSER_JOB_RELAY_BLOCK_MS = 1000

# The ARQ function name, shared by the enqueue site and the worker registration.
BROWSER_JOB_TASK = "run_browser_job"
