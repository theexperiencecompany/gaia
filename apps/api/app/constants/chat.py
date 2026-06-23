"""Chat persistence constants."""

import re

# Max characters of an uploaded file's summary inlined into the agent's turn
# context. The full summary lives in the `<file>.summary.md` sidecar; this is a
# defensive cap so a long page-wise summary can't bloat the prompt.
UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS = 600

# Matches bot-emitted artifact references in three shapes — ``./artifacts/x``,
# ``/artifacts/x``, and plain ``artifacts/x`` — so each can be rewritten to an
# absolute backend URL. The reference must sit at the start of the string or
# right after whitespace, a quote, or an opening paren (markdown image links,
# OpenUI string args, plain prose). Anchoring on those delimiters — rather than
# "any non-word char" — keeps ``myartifacts/`` AND query strings like
# ``?file=artifacts/report.pdf`` from being mangled.
ARTIFACT_REF_RE = re.compile(
    r"""(?P<lead>^|[\s'"`(])(?P<prefix>\.\/|\/)?artifacts\/(?P<path>[A-Za-z0-9._\-/]+)""",
    re.VERBOSE,
)

# Matches a fully-qualified in-sandbox artifact path
# (``/workspace/sessions/<id>/artifacts/<name>``). An agent that reports an
# absolute path can only mean THIS conversation's artifact, so it is rewritten
# to the current conversation's backend URL regardless of the ``<id>`` written —
# which also self-heals a fabricated/mismatched session id.
WORKSPACE_ARTIFACT_RE = re.compile(
    r"/workspace/sessions/[A-Za-z0-9._-]+/artifacts/(?P<path>[A-Za-z0-9._\-/]+)"
)
