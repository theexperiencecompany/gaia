"""Chat constants."""

import re

# Sized so small files (images, short PDFs) come through in full; only large
# multi-page summaries truncate, with the full text in the `<file>.summary.md` sidecar.
UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS = 4000

# Upper bound for a single incoming chat message, rejected at the request
# boundary. Generous on purpose: the web composer converts pastes over ~10k
# chars into .txt attachments, so normal traffic never gets near this.
MAX_MESSAGE_LENGTH = 50_000

# ``MessageModel.type`` of a message the human wrote (the other value is
# ``"bot"``). Named so a stored-message query and the writers agree on the literal.
USER_MESSAGE_TYPE = "user"

# Shown when a turn dies and the provider exception carries no message of its
# own. Names the exception type so a support report still identifies the failure.
GENERIC_TURN_ERROR = "Something went wrong while generating this response ({error_type})."

# Shown when the model produced no text at all (reasoning-only output,
# max_tokens exhausted mid-thought, a content filter) — a blank bubble reads as "it ignored me".
EMPTY_RESPONSE_FALLBACK = "that didn't come through, say it again?"

# A recursion-limit stop is an expected degradation, not an infrastructure
# failure — never show the raw "Recursion limit of N reached..." internals.
RECURSION_LIMIT_MESSAGE = (
    "I hit my step limit on this one before finishing. "
    "Ask me to continue and I'll pick up where I left off."
)

# Matches `./artifacts/x`, `/artifacts/x`, and plain `artifacts/x` at the start
# of the string or right after whitespace/quote/paren. Anchoring there — rather
# than "any non-word char" — keeps `myartifacts/` and `?file=artifacts/report.pdf` from being mangled.
ARTIFACT_REF_RE = re.compile(
    r"""(?P<lead>^|[\s'"`(])(?P<prefix>\.\/|\/)?artifacts\/(?P<path>[A-Za-z0-9._\-/]+)""",
    re.VERBOSE,
)

# Matches a fully-qualified in-sandbox artifact path. Rewritten to the current
# conversation's backend URL regardless of the `<id>` written, which also self-heals a mismatched session id.
WORKSPACE_ARTIFACT_RE = re.compile(
    r"/workspace/sessions/[A-Za-z0-9._-]+/artifacts/(?P<path>[A-Za-z0-9._\-/]+)"
)
