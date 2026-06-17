"""Chat persistence constants."""

import re

# Matches bot-emitted artifact references in three shapes — ``./artifacts/x``,
# ``/artifacts/x``, and plain ``artifacts/x`` — so each can be rewritten to an
# absolute backend URL. Allows a quote, paren or whitespace right before
# (markdown image links, OpenUI string args, plain prose) but requires no
# leading "word" character so ``myartifacts/`` is never mangled.
ARTIFACT_REF_RE = re.compile(
    r"""(?P<lead>(?<![A-Za-z0-9_/])|(?<=['"`(\s]))(?P<prefix>\.\/|\/)?artifacts\/(?P<path>[A-Za-z0-9._\-/]+)""",
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
