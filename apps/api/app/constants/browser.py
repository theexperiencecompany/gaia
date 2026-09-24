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


class EngineFailure(StrEnum):
    """How the browser engine under a run failed it, as its host reports it.

    Either one sends the run to the fallback engine; a run that failed on an
    engine still serving its session did not fail because of the engine.
    """

    #: The engine process died or the host lost the session: 404, or not live.
    SESSION_GONE = "session_gone"
    #: The host did not answer for the session: the engine is wedged or the host is down.
    UNRESPONSIVE = "unresponsive"


class StateCarry(StrEnum):
    """Whether a run moving to the fallback engine took the primary's live cookies and localStorage with it."""

    CARRIED = "carried"
    #: The primary engine had already failed under the run, so there was nothing to read.
    ENGINE_FAILED = "engine_failed"
    #: Reading the primary failed: the host lost the session or did not answer.
    UNREADABLE = "unreadable"


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


class HandoffKind(StrEnum):
    """Who a paused run is waiting on: the user in live view, or the executor that started it.

    USER is the default so records written before agent guidance existed parse.
    An AGENT record never takes the conversation's pending-handoff key, which is
    what makes a chat reply resolve a handoff.
    """

    USER = "user"
    AGENT = "agent"


class BrowserLoginSource(StrEnum):
    """Where a saved login came from.

    Absent for logins acquired by browsing; stamped on the per-host docs the
    gaia connect CLI import writes."""

    IMPORT = "import"


# Defined here rather than beside JevOperation because BROWSER_TAKEOVER_PREAMBLE
# below interpolates it at import time.
class BrowserHandoffAction(StrEnum):
    """The actions GAIA registers with Browser-Use to hand a step off: two to the human, one to the agent that started the run."""

    REQUEST_HUMAN_TAKEOVER = "request_human_takeover"
    SOLVE_CAPTCHA_WITH_HELP = "solve_captcha_with_help"
    REQUEST_AGENT_GUIDANCE = "request_agent_guidance"


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
# Why the run woke up when nobody tapped "done". The run tells it apart from a
# note the user typed, which redirects the task and the closing reply with it.
HANDOFF_AUTORESOLVED_NOTE = "Looks like you're done here, resuming."
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
BROWSER_HANDOFF_ACK_REDIRECT = "Got it, continuing with that instead."

# A run summary that was stopped on purpose leads with this label; the bot strips
# it so "Couldn't finish that:" never stacks a second stop-word on top.
BROWSER_RUN_STOPPED_LABEL = "Stopped: "

# An expired handoff is a failed run, not the completed one a takeover made it look like.
BROWSER_RUN_HANDOFF_TIMED_OUT = (
    f"{BROWSER_RUN_STOPPED_LABEL}nobody finished the step in the live browser in time."
)

# Reaches the user verbatim on the failure card, so it reads like a person. Shared
# by the Jev BLOCKED action and the run that ends because no guidance arrived.
BROWSER_RUN_BLOCKED_SUMMARY = "I couldn't find a way to move forward on this page."

# Fixed copy, no exception text: many exceptions stringify to "", which left
# "...stopped unexpectedly:" dangling in front of the user.
BROWSER_JOB_CRASHED_SUMMARY = (
    "the browser task stopped unexpectedly, and nothing else changed; you can ask me to try again"
)

# Upper bound on how many times one task may hand off to the human, so a
# misbehaving agent can't loop the user forever.
MAX_HANDOFFS_PER_TASK = 5

# --- Agent guidance ---

# Asked of the joined executor instead of failing; bounded so a run that cannot
# be unstuck does not ping-pong with it.
BROWSER_AGENT_GUIDANCE_MAX = 3
BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS = 120
# The only thing the user sees of the round trip: the step frame's caption.
BROWSER_AGENT_GUIDANCE_CAPTION = "Working out another way"
# The pending request a joined executor reads, keyed by job. Not a card frame:
# the relay would put it on the user's stream, and a replayed feed would fire it twice.
BROWSER_JOB_GUIDANCE_PREFIX = "browser:job:guidance:"
# Tighter than JEV_PAGE_TEXT_MAX_CHARS: this rides inside one executor tool result.
BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS = 1500
BROWSER_GUIDANCE_MAX_ELEMENTS = 40
BROWSER_GUIDANCE_RECENT_ACTIONS = 6
# The fixed copy of the request a joined executor reads (agent_guidance.guidance_message).
# Named here so the render is tested for where each part lands, not for its wording.
BROWSER_GUIDANCE_HEADER = "THE BROWSER TASK IS STUCK and is waiting for one instruction from you."
BROWSER_GUIDANCE_CHANGED_INSTRUCTION = (
    "MID-RUN THE USER CHANGED THE INSTRUCTION to {changed}. That is what your guidance "
    "must serve. Where the task below conflicts with it, the task is no longer wanted, "
    "and you must never send the run back to a step the user declined."
)
BROWSER_GUIDANCE_ANSWER = (
    "Answer with exactly one of these, then call wait_for_browser_task() again:\n"
    '  guide_browser_task("<one concrete instruction>") -- what to click, what to '
    "type, where to navigate, or the fact to use. One step, not a plan. Use only "
    "facts from this conversation, the user's request and your memory; never invent "
    "one. Prefer a different route over repeating what already failed: a wall on "
    "one page rarely blocks the site's direct address for the same content.\n"
    '  guide_browser_task(give_up=True, reason="<why it cannot be done>") -- only '
    "when no route is left, never because a step the user already declined is blocked."
)

# Two failed steps running end the run with its reason, not Browser-Use's narrowing to done.
BROWSER_AGENT_MAX_FAILURES = 2
# A decision can wait out a layout pass, a part judgement and Jev; Browser-Use's 75s cut it off.
BROWSER_AGENT_LLM_TIMEOUT_SECONDS = 180

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


class JevNoteSource(StrEnum):
    """Who wrote the instruction attached to a step: the user, or the agent that planned the task."""

    USER = "user"
    AGENT = "agent"


# A step that shows nothing for this long gets one line saying so. The Berlin
# article measured 40 to 71 s of clean render with no error left to caption.
BROWSER_STALL_NOTE_AFTER_SECONDS = 25.0
BROWSER_STALL_NOTE = "Still waiting on the page, it's a slow one."

# Said once when a run moves to the fallback engine, so the steps that follow
# on another browser do not read as the run starting over.
BROWSER_ENGINE_FALLBACK_NOTE = (
    "That page didn't work in the fast browser, continuing in a full one."
)
# The same, when the fast browser's state could not come along.
BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE = (
    "That page didn't work in the fast browser, continuing in a full one. "
    "It starts from your saved logins only, so you may need to sign in again."
)

# Engine watchdog: the primary engine's liveness is read this often, and this
# many unanswered reads in a row end the run there. Without it a SIGSTOPped
# engine took ~285 s to notice (a 15 s click timeout, then two 120 s state reads).
BROWSER_ENGINE_WATCH_INTERVAL_SECONDS = 10.0
BROWSER_ENGINE_WATCH_STRIKES = 2
# How long a run cut short by the watchdog may take to unwind before the switch
# goes ahead without it; Browser-Use's cleanup talks to the frozen engine too.
BROWSER_ENGINE_WATCH_CANCEL_GRACE_SECONDS = 5.0

# The host answers a liveness read inside its own budget, whatever the engine is
# doing, and the client allows it a little more before calling it unanswered.
BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS = 3.0
BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS = 5.0
# The outcome of a run the user stopped while its engine was frozen; never shown,
# since a stopped run's card reads the stop.
BROWSER_ENGINE_UNRESPONSIVE_SUMMARY = "The browser stopped responding."

# How a decision taken on the handoff card is written into the agent's thread,
# so the reply it later voices knows the user changed course.
BROWSER_HANDOFF_CARD_DECISION = "[From the browser handoff card] {decision}"

# The user's own request rides along with the executor's task text, clipped to
# this many characters; the executor rewrote "tick the second checkbox" into an
# invented label twice and the browser skipped the step both times.
BROWSER_USER_WORDS_MAX_CHARS = 1000

# Jev sees the viewport only; this bounds one screen. Measured on Wikipedia:
# 200 rows is 64,483 bytes, the gateway 400s max_tokens_exceeded from 86,133
# bytes up, and refuses a question with over 255 choices.
JEV_MAX_ELEMENTS = 100

JEV_GATEWAY_TIMEOUT_SECONDS = 8.0
# One writer call's budget, and when an identical hedge request is sent if the
# first has not answered (first answer wins). Measured 2026-09-23: p50 3 s,
# p90 17 s, max 59 s, the slow tail from one upstream provider.
JEV_TEXT_TIMEOUT_SECONDS = 30.0
JEV_TEXT_HEDGE_SECONDS = 8.0
JEV_CLOSING_ANSWER_HEDGE_SECONDS = 30.0
# The closing answer carries every page read and action of the run, so it gets
# a longer budget and a second attempt: at 60 s a 13-minute research task once
# ended without one on a slow link.
JEV_CLOSING_ANSWER_TIMEOUT_SECONDS = 150.0
JEV_GATEWAY_MAX_ATTEMPTS = 3

# Observation budget: visible page text sent as Jev state, and how much of the
# run's own action history rides along as context.
JEV_PAGE_TEXT_MAX_CHARS = 6000
# What the closing answer may read back across every page the run opened, on
# top of the current screen. Bounded because the whole of it rides on one
# writer call; 18000 made that call the slowest in the run.
JEV_SEEN_TEXT_MAX_CHARS = 8000
JEV_ELEMENT_LABEL_MAX_CHARS = 120
JEV_RECENT_ACTIONS = 10
# Pages already opened and read that Jev is shown, so a list task moves to its next item.
JEV_PAGES_READ = 12
# A compound task is split into at most this many ordered parts before the first decision.
JEV_PLAN_MAX_STEPS = 6
JEV_TEXT_HELPER_RECENT_ACTIONS = 6
# The closing answer sees the run's actions, so it reports only what was actually done.
JEV_CLOSING_ANSWER_ACTIONS = 60
JEV_TEXT_VALUE_MAX_CHARS = 2000
# Stands in for a value typed into a password field wherever the run's text reaches a person.
JEV_SECRET_MASK = "[hidden]"
# The closing answer covers every part of a task; a typed value's cap is far too small for it.
JEV_SUMMARY_MAX_CHARS = 6000
# Probability mass across a choice question must sum to ~1; the gateway rounds.
JEV_PROBABILITY_SUM_TOLERANCE = 0.02

# How long each WAIT in a row on one page waits. Browser-Use sleeps one second
# less than asked, so a wait of 1 slept nothing and three of them declared a page
# done 4 s after the click that started its 5 s loader.
JEV_WAIT_SECONDS = (3, 6, 10)


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
# to answer "is it still running?". Outlives the turn; its TTL is
# app.services.browser.job_lifetime.browser_job_ttl_seconds.
BROWSER_JOB_STATE_PREFIX = "browser:job:"
# A job's time outside the run's own clock: opening the session (and the fallback
# engine's), the terminal writes, the wait for a joiner and narrating the result.
BROWSER_JOB_OVERHEAD_SECONDS = 300
# How long a finished job's state, feed and flags stay readable after the latest
# the job could have ended.
BROWSER_JOB_RETENTION_SECONDS = 3600

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
# Browser jobs have their own ARQ queue and worker (app.workers.browser_worker).
BROWSER_JOB_QUEUE = "arq:queue:browser"


# ---------------------------------------------------------------------------
# Observability: the reason codes a run's and a host request's wide event carry.
# ---------------------------------------------------------------------------


class BrowserRunFailure(StrEnum):
    """Why a browser run did not succeed; the worker event's reason field."""

    BLOCKED = "blocked"
    NEVER_OPENED = "never_opened"
    GOAL_NOT_ACHIEVED = "goal_not_achieved"
    HANDOFF_TIMEOUT = "handoff_timeout"
    CANCELLED = "cancelled"
    TASK_TIMEOUT = "task_timeout"
    ENGINE_CRASH = "engine_crash"
    LLM_ERROR = "llm_error"
    HOST_UNAVAILABLE = "host_unavailable"
    HOST_AT_CAPACITY = "host_at_capacity"
    RUN_CRASHED = "run_crashed"


# Why a run moved to the fallback engine when its engine did not fail: a page it
# could not pass. The engine-failure reasons are EngineFailure's values.
BROWSER_FALLBACK_PAGE_BLOCKED = "page_blocked"


class HostRequestFailure(StrEnum):
    """Why the browser host refused a request; its request event's reason field."""

    INVALID_HOST_KEY = "invalid_host_key"
    SESSION_NOT_FOUND = "session_not_found"
    AT_CAPACITY = "at_capacity"
    ENGINE_UNRESPONSIVE = "engine_unresponsive"


class HostAdmissionRefusal(StrEnum):
    """Which admission gate turned a session create away."""

    SESSION_CEILING = "session_ceiling"
    MEMORY = "memory"


# Browser-Use's own env switches (browser_use/config.py), forced off in every GAIA
# process: the telemetry sends usage to its PostHog, the version check costs a
# PyPI request (up to 3 s) on every run. Cloud sync follows telemetry's value.
BROWSER_USE_PHONE_HOME_OFF: dict[str, str] = {
    "ANONYMIZED_TELEMETRY": "false",
    "BROWSER_USE_VERSION_CHECK": "false",
}
