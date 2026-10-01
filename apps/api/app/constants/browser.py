"""Constants for the Browser-Use browser-automation capability.

Single source of truth for the SSE card-event keys, the Redis key namespaces,
the run's bounds and the copy the agent, the executor and the user read.
Values a deployment may tune live in settings; values that are part of the
wire/UI contract live here so backend and frontend cannot drift.

The startup gate ("do you want me to use a browser?") is handled by the shared
HIL system (browser_task is registered destructive). Mid-run, the agent itself
decides when a payment, credential, CAPTCHA or irreversible step goes to the
user, through its handoff actions.
"""

from enum import Enum, StrEnum
from typing import Literal

# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------
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


class EngineSwitchReason(StrEnum):
    """Why the agent moved an Obscura run to Chrome: the kinds of breakage the fast engine causes."""

    RENDERS_WRONG = "renders_wrong"
    CONTROL_BROKEN = "control_broken"
    STAYS_EMPTY = "stays_empty"


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
    """Lifecycle state of a browser session: working, then how it ended."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SensitiveCategory(str, Enum):
    """Why a planned browser step is sensitive."""

    NONE = "none"
    PAYMENT = "payment"
    CREDENTIALS = "credentials"
    IRREVERSIBLE = "irreversible"


# Shown on a CREDENTIALS handoff where BROWSER_PERSIST_LOGINS keeps logins: the
# session is saved (Fernet-encrypted per user+site) and reused so the next task
# skips the login. The Browser settings page can list/remove saved sites.
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
HANDOFF_KEY_TTL_SECONDS = 3600
# The last line of a handoff a bot user is sent: only their word ends it.
BROWSER_HANDOFF_REPLY_PROMPT = "Reply here when you're done, or tell me to stop."
# A host session lives on a lease the run renews while its job is alive, paused
# or not; one it stops renewing (its worker died) is disposed when the lease runs out.
BROWSER_SESSION_LEASE_SECONDS = 90.0
# Three renewals per lease, so one slow or lost renewal never costs a live run its browser.
BROWSER_SESSION_LEASE_RENEW_SECONDS = BROWSER_SESSION_LEASE_SECONDS / 3

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

# Step frames kept in Redis when no object store is configured, served back
# through a code of their own so the frames are not enumerable by session id.
# One code per run: code -> run, and run -> code so every step reuses it.
BROWSER_SHOT_CODE_KEY_PREFIX = "browser:shotcode:"
BROWSER_SHOT_SESSION_KEY_PREFIX = "browser:shotsess:"
BROWSER_SHOT_FRAME_KEY_PREFIX = "browser:shot:"

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

# Chat acks when a handoff is resolved by a natural-language reply.
BROWSER_HANDOFF_ACK_CONTINUE = "Got it, continuing the browser task."
BROWSER_HANDOFF_ACK_CANCEL = "Okay, I've stopped the browser task."

# An expired handoff is a failed run, not the completed one a takeover made it look like.
BROWSER_RUN_HANDOFF_TIMED_OUT = "Stopped: nobody finished the step in the live browser in time."
# The run asked the user to take over more often than one task may.
BROWSER_RUN_HANDOFF_LIMIT_SUMMARY = (
    "Stopped: the task needed you to take over more than {limit} times, the most one task may."
)

# Reaches the user verbatim on the failure card of a run that ended because no
# guidance arrived, so it reads like a person.
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
# Tighter than a Jev observation's text: this rides inside one executor tool result.
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

# The browser agent's reasoning effort on any lane: it steers and signs off, Jev does the stepping.
BROWSER_AGENT_REASONING_EFFORT: Literal["low"] = "low"
BROWSER_AGENT_OPENROUTER_KEY_MISSING = "OPENROUTER_API_KEY is not set; the browser agent needs it."
# When a browser model call gets an identical second request (first answer wins). Agent
# calls measured p50 3.2 s, p90 4.5 s, with stalls past the 180 s timeout (2026-09-25).
BROWSER_AGENT_HEDGE_SECONDS = 12.0
# Browser-Use shortens any URL whose query passes 25 characters in what the model
# reads ("?my-text=Aryan&my-pass...1a2b3c4"), so a run asked for the page it landed
# on reported it could not see it (battery form, 2026-09-25). Room for any real query.
BROWSER_AGENT_URL_QUERY_MAX_CHARS = 2000
# A top-level load whose server sends nothing for this long is stopped, as a person
# presses Stop: until it answers, Chrome answers no script on the tab (measured 2026-09-25).
BROWSER_LOAD_STALL_SECONDS = 15.0
BROWSER_LOAD_STOP_TIMEOUT_SECONDS = 5.0
#: What the agent reads about a load the browser stopped: the plain fact, no retry rule.
BROWSER_LOAD_STALLED_NOTE = (
    "{url} did not respond within {seconds:.0f} s, so its loading was stopped and the tab "
    "stayed on the page it was on."
)
#: What the agent reads about a page Browser-Use read before its load had finished.
BROWSER_LOAD_UNFINISHED_NOTE = (
    "{url} had not finished loading (its load event had not fired) when the browser stopped "
    "waiting for it, so the step went on with the page as it was then."
)
# The longest one model call may take; Browser-Use's 75 s default cut off decisions on slow pages.
BROWSER_AGENT_LLM_TIMEOUT_SECONDS = 180

# Appended to every browser task so the agent uses the takeover action instead
# of doing sensitive steps itself.
BROWSER_TAKEOVER_PREAMBLE = (
    "\n\nIMPORTANT: For a payment, a login whose credentials this task does not give as "
    "<secret>name</secret> placeholders, an OTP/2FA code, or an irreversible or "
    "legally-binding confirmation the task did not ask for, do NOT do it yourself. Call the "
    f"`{BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER}` action so the user completes that step in the "
    "live browser, then continue toward the goal. A login whose credentials the task gives "
    "is done by the run itself, never handed over.\n"
    "If you encounter a CAPTCHA, reCAPTCHA, hCaptcha, or an 'I'm not a robot' / "
    "image-grid challenge, do NOT attempt to solve it yourself. When the task cannot be "
    f"done without passing it, call the `{BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP}` action "
    "on the FIRST challenge so the user solves it in the live browser, then continue. When "
    "the blocked page is only one of several sources the task can use, skip it, carry on "
    "with the others, and say which page could not be opened. Never keep clicking "
    "challenge tiles.\n"
    # The human's part of a login should be only the secret part.
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
    "values are fine.\n"
    # The agent reported only "Received!" for a page whose heading is "Form submitted"
    # in about a third of runs while this sat in the system prompt.
    "When you report what a page shows, says or displays, quote all of its visible text that "
    "answers that, the page's heading included: a result page's title and its message."
)

# The agent's role around Jev, appended to Browser-Use's system prompt.
BROWSER_AGENT_ROLE = (
    "You supervise Jev, a fast page operator exposed as the `jev` action. Your step 0 "
    "already ran Jev on the whole task; its report (actions, where it stopped and why, and "
    "the text of the page it ended on) is in your history. You are the only one who finishes the "
    "task and the only one who writes the answer.\n"
    "Each step, choose one:\n"
    "1. The task is complete: call `done` with the answer. Report only what the current "
    "page or Jev's reports show; copy titles, messages, numbers and URLs exactly. "
    "Say plainly what was not done or could not be found. Set success=false when the task "
    "was not achieved.\n"
    "2. A sequence of interactions remains (filling a form, searching and choosing, clicking "
    "through several pages): call `jev` with a sharper, self-contained goal for what "
    "remains, quoting every value to type. Never repeat a goal Jev made no progress on.\n"
    "3. A single step remains, or something Jev cannot do: do it yourself. Navigate to a URL "
    "you already know, click once, switch tabs, read or summarise a page with `extract` (to "
    "read a linked page, navigate to its exact URL from Jev's report or a `find_elements` href, "
    "then extract; never guess a URL), "
    "search a long page with `search_page`, count with `find_elements` (a CSS selector "
    "returns every match), never count by eye.\n"
    "Work through every part of the task before you finish: a part is reported as not done "
    "only after you tried it and it could not be done.\n"
    "Logins without given credentials, payments, OTPs and CAPTCHAs go to the user through "
    "the handoff actions. Messages the user sends mid-task arrive as follow-up requests: "
    "they change the task from then on."
)

#: What the agent reads after a handoff step when the user left no note.
BROWSER_TAKEOVER_DONE_NOTE = (
    "The user says they finished that step in the live browser. If the page still asks "
    "for it, hand it to them again."
)
#: How a run's result reads when the runner, not the agent, ended it.
BROWSER_RUN_WALL_CLOCK_SUMMARY = "Browser task timed out after {seconds}s."
BROWSER_RUN_WORK_BUDGET_SUMMARY = "Browser task timed out after {seconds}s of work."
BROWSER_RUN_STOPPED_SUMMARY = "Browser task stopped."
BROWSER_RUN_CANCELLED_SUMMARY = "Browser task was cancelled."
BROWSER_RUN_DONE_SUMMARY = "Completed the browser task."
BROWSER_RUN_NOT_DONE_SUMMARY = "Could not complete the browser task."
#: Logged when the agent could not attach to a session the host created: nearly always the CDP proxy.
BROWSER_CDP_ATTACH_HINT = (
    "Check that the browser host is reachable from the API at BROWSER_HOST_URL."
)
#: What the user reads when the agent never attached to the browser.
BROWSER_CDP_ATTACH_FAILED = "Could not connect to the browser."
#: What the user reads when the run failed on an unexpected error; the error itself is logged.
BROWSER_RUN_CRASHED_SUMMARY = "The browser task stopped on an unexpected error."
#: Why a run cannot start when no Chromium host is configured for it.
BROWSER_NO_CHROME_HOST = "No Chrome browser host is configured (BROWSER_FALLBACK_HOST_URL)."
#: Said to the agent when it asks for guidance and none can be asked: no assistant joined, or none left.
BROWSER_NO_GUIDANCE_AVAILABLE = (
    "No guidance is available. Decide yourself: act, re-delegate to jev, or finish "
    "with an honest account of what could not be done."
)

# Desktop viewport (the ~800x600 CDP default collapses sites to mobile layout). The live
# view caps its stream at this same size (screencast.py imports it): wider only buys a
# downscaled stream, a takeover coordinate mismatch and bigger vision payloads.
BROWSER_VIEWPORT_WIDTH = 1280
BROWSER_VIEWPORT_HEIGHT = 800
#: CSS pixels per screen pixel: shots and click points share one coordinate space.
BROWSER_DEVICE_SCALE_FACTOR = 1


# --- Jev decision policy ---
class JevOperation(StrEnum):
    """One Jev choice per step; CLICK, TYPE_TEXT and SELECT also carry an observed target."""

    CLICK = "CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    SELECT = "SELECT"
    PRESS_ENTER = "PRESS_ENTER"
    SCROLL_DOWN = "SCROLL_DOWN"
    SCROLL_UP = "SCROLL_UP"
    WAIT = "WAIT"
    NAVIGATE = "NAVIGATE"
    GO_BACK = "GO_BACK"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class JevStop(StrEnum):
    """Why a Jev burst handed control back to the agent."""

    DONE = "done"
    BLOCKED = "blocked"
    NEEDS_INPUT = "needs_input"
    SECRET_WITHHELD = "secret_withheld"
    NO_PROGRESS = "no_progress"
    CYCLE = "cycle"
    MAX_ACTIONS = "max_actions"
    MAX_DECISIONS = "max_decisions"
    COVERED = "covered"
    STALE = "stale"
    UNRESPONSIVE = "unresponsive"
    USER_MESSAGE = "user_message"
    STOPPED = "stopped"
    GATEWAY = "gateway"
    LOAD_STALLED = "load_stalled"
    NAVIGATION_FAILED = "navigation_failed"
    FIELD_UNFOCUSED = "field_unfocused"
    TAB_UNAVAILABLE = "tab_unavailable"
    PAGE_SCRIPT_ERROR = "page_script_error"


#: Controls offered to Jev per request, in DOM order within the viewport. Vercel's
#: gateway 503s from ~130 elements; OpenRouter answered 150 in ~350 ms.
JEV_MAX_ELEMENTS = 120
JEV_GATEWAY_TIMEOUT_SECONDS = 8.0
JEV_GATEWAY_MAX_ATTEMPTS = 3
#: After a 402 (out of credit) the failover client skips that gateway this long.
JEV_OUT_OF_CREDIT_SECONDS = 300.0
#: How much of the final page's visible text a burst report hands the agent, and of each
#: other page the burst opened (the most recent ones, up to the count).
JEV_REPORT_PAGE_TEXT_CHARS = 2000
JEV_REPORT_OPENED_PAGE_CHARS = 1500
JEV_REPORT_OPENED_PAGES = 6
JEV_RECENT_ACTIONS = 10
JEV_VISITED_PAGES = 12
#: One burst's bounds, from jev-ultrafast: actions, unchanged non-wait actions in a
#: row, and consecutive stale or covered targets before the agent takes over.
JEV_BURST_MAX_ACTIONS = 25
#: Decisions (paid model calls) per burst, as jev-ultrafast bounds them: none may loop unbounded.
JEV_BURST_MAX_DECISIONS = 2 * JEV_BURST_MAX_ACTIONS
JEV_UNCHANGED_LIMIT = 3
JEV_STALE_LIMIT = 3
JEV_COVERED_LIMIT = 2
#: Snapshot reads while a navigation replaces the document; Chrome holds each until the new one commits.
JEV_OBSERVE_ATTEMPTS = 50
#: Longest any one of Jev's CDP calls may take; a page or session that does not answer
#: ends the burst instead of holding it until the task's budget runs out.
JEV_CDP_TIMEOUT_SECONDS = 20.0
#: The longest an explicit WAIT waits for the page to change at all.
JEV_WAIT_SECONDS = 1.0
#: The longest the read after an input waits for its requests to finish and the DOM to go quiet:
#: a page that animates or polls never does.
JEV_SETTLE_MAX_SECONDS = 2.0
JEV_SCREENSHOT_QUALITY = 70
#: The tiny model writes a value only when no literal from the goal fits; it reads this much page text.
JEV_TEXT_TIMEOUT_SECONDS = 30.0
JEV_TEXT_HEDGE_SECONDS = 6.0
JEV_TEXT_OPENROUTER_KEY_MISSING = (
    "OPENROUTER_API_KEY is not set; Jev decisions and the text model both need it."
)
JEV_PAGE_TEXT_MAX_CHARS = 6000
JEV_TEXT_VALUE_MAX_CHARS = 2000
# Stands in for a value typed into a password field wherever the run's text reaches a person.
JEV_SECRET_MASK = "[hidden]"  # nosec B105 -- the placeholder shown in place of a typed password, not a credential
#: What a step says a password field holds when it is not the secret typed: never its value.
JEV_SECRET_DIFFERS = "a value other than the secret"  # nosec B105 -- report wording, not a credential
# Probability mass across a choice question must sum to ~1; the gateway rounds.
JEV_PROBABILITY_SUM_TOLERANCE = 0.02


# A step that shows nothing for this long gets one line saying so. The Berlin
# article measured 40 to 71 s of clean render with no error left to caption.
BROWSER_STALL_NOTE_AFTER_SECONDS = 25.0
BROWSER_STALL_NOTE = "No update from the browser for {seconds} s."

# What the agent's continue_in_full_browser call answers: the run ends here and resumes there.
BROWSER_ENGINE_SWITCH_ACK = (
    "Moving this task to the full browser. It continues there from this page."
)
#: What the agent reads first on the fallback engine, its earlier steps still in its history.
BROWSER_ENGINE_RESUMED_NOTE = (
    "This run moved to the full browser (Chrome), which opened {page}. Continue the task "
    "from there."
)
#: What a handoff action answers: the wait runs once the step ends, outside its step budget.
BROWSER_ANSWER_AFTER_STEP = "Asked. The answer arrives before your next step."
# Said once when a run moves to the fallback engine, so the steps that follow
# on another browser do not read as the run starting over.
BROWSER_ENGINE_FALLBACK_NOTE = (
    "That page didn't work in the fast browser, continuing in a full one."
)
# The same, when the fast browser's state could not come along.
BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE = (
    "That page didn't work in the fast browser, continuing in a full one. "
    "Sign-ins from this run could not come along, so a site may ask you to sign in again."
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

# ---------------------------------------------------------------------------
# Background browser job
# ---------------------------------------------------------------------------

# One browser task per conversation; the value is the job id so a refused second
# task can name the run the user is already watching. A heartbeat lease, not a
# fixed TTL: a run may sit a whole handoff window (BROWSER_USE_HANDOFF_TIMEOUT_SECONDS) paused, a dead worker must not.
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
# What the user said while a job runs, oldest first: the run reads it between steps.
BROWSER_JOB_INBOX_PREFIX = "browser:job:inbox:"

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
    #: The agent finished and said the task was not achieved.
    GOAL_NOT_ACHIEVED = "goal_not_achieved"
    #: The agent never finished: its last step ended in an error.
    STEP_FAILED = "step_failed"
    #: The agent never finished: it used every step Browser-Use allows.
    STEP_LIMIT = "step_limit"
    HANDOFF_TIMEOUT = "handoff_timeout"
    HANDOFF_LIMIT = "handoff_limit"
    CANCELLED = "cancelled"
    TASK_TIMEOUT = "task_timeout"
    COST_BUDGET = "cost_budget"
    HOST_UNAVAILABLE = "host_unavailable"
    HOST_AT_CAPACITY = "host_at_capacity"
    RUN_CRASHED = "run_crashed"


class HostRequestFailure(StrEnum):
    """Why the browser host refused a request; its request event's reason field."""

    INVALID_HOST_KEY = "invalid_host_key"
    INVALID_SESSION_TOKEN = "invalid_session_token"
    SESSION_NOT_FOUND = "session_not_found"
    AT_CAPACITY = "at_capacity"
    ENGINE_UNRESPONSIVE = "engine_unresponsive"
    ENGINE_REFUSED = "engine_refused"
    DEADLINE_EXCEEDED = "deadline_exceeded"


class HostAdmissionRefusal(StrEnum):
    """Which admission gate turned a session create away."""

    SESSION_CEILING = "session_ceiling"
    MEMORY = "memory"


class HostSessionEnd(StrEnum):
    """How a session left the browser host; the operation its wide event carries."""

    DISPOSED = "dispose"
    LEASE_EXPIRED = "lease_expired"
    CONNECTION_LOST = "connection_lost"
    ENGINE_LOST = "engine_lost"


# The header every browser-host REST call carries the shared host key in.
BROWSER_HOST_KEY_HEADER = "X-Host-Key"
# The header a host client sends its own deadline in, so the host finishes or gives
# up inside it instead of working on for a caller that has stopped listening.
BROWSER_HOST_DEADLINE_HEADER = "X-Host-Deadline"


# Browser-Use's own env switches (browser_use/config.py), forced off in every GAIA
# process: the telemetry sends usage to its PostHog, the version check costs a
# PyPI request (up to 3 s) on every run. Cloud sync follows telemetry's value.
BROWSER_USE_PHONE_HOME_OFF: dict[str, str] = {
    "ANONYMIZED_TELEMETRY": "false",
    "BROWSER_USE_VERSION_CHECK": "false",
}

# Browser-Use's own per-event budgets (its TIMEOUT_<Event> overrides), as defaults
# an operator's environment still overrides. They are process-wide: Browser-Use
# creates these events itself, so no budget can be set per session.
BROWSER_USE_EVENT_TIMEOUTS: dict[str, str] = {
    # A first capture of a very long page took 24 to 35 s on Obscura (2026-09-19),
    # past Browser-Use's 15 s.
    "TIMEOUT_ScreenshotEvent": "60",
    # Every step's state read carries that screenshot: its budget plus Browser-Use's
    # own 30 s for the rest of the read.
    "TIMEOUT_BrowserStateRequestEvent": "90",
}
