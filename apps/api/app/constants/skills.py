"""Skills domain constants.

Single source of truth for the skill catalog's on-disk filenames, the special
"executor" bucket id, the builtin library location, and the SKILL.md frontmatter
parsers. Imported by the skill loader, the workspace materializers, the system-
file index, and the discovery service so these values can never drift apart.
"""

import re

# Source filename authored in the repo for each builtin skill
# (apps/api/app/agents/skills/builtin/<slug>/SKILL.md).
SKILL_SOURCE_FILENAME = "SKILL.md"

# Filename of the materialized skill body inside each slug dir on the workspace
# (e.g. integrations/<id>/agent/skills/<slug>/skill.md). Shared by the
# materializer (storage.sessions.skills), the system-file index, and discovery
# so the path the agent is told to read always matches the file on disk.
SKILL_BODY_FILENAME = "skill.md"

# Bucket id for general builtin skills not owned by an integration subagent
# (create-artifacts, task-management, …). It is NOT a registered subagent: it
# maps to itself and its skills materialize under /workspace/skills/ rather than
# /workspace/integrations/<id>/.
EXECUTOR_SUBAGENT_ID = "executor"

# User-facing label for the executor target in the skills UI. The executor is
# the general assistant (not a registered integration subagent), so it needs an
# explicit display name where subagents get theirs from the subagent registry.
EXECUTOR_TARGET_LABEL = "General assistant"

# Builtin SKILL.md library location, relative to the app/agents/ package dir.
SKILLS_PACKAGE_DIRNAME = "skills"
BUILTIN_SKILLS_DIRNAME = "builtin"

# --- SKILL.md frontmatter parsing -------------------------------------------
# Input is a trusted, bounded builtin SKILL.md frontmatter block bundled in the
# repo — never user-supplied — so the lazy `.*?` cannot be driven into pathological
# backtracking by an adversary.
SKILL_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)  # NOSONAR python:S5852
# Forgiving YAML reader: builtins only ever use scalar key: value pairs and we
# don't want to depend on PyYAML in this hot path. The leading-whitespace gap is
# matched possessively (`\s*+`) so it never backtracks into the value group,
# keeping the match linear. Trailing whitespace is stripped by the caller.
SKILL_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_]\w*):\s*+(.+)$")
