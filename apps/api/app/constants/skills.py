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

# Filename of the materialized skill body on the workspace (e.g.
# integrations/<id>/agent/skills/<slug>/skill.md). Shared by the materializer,
# system-file index, and discovery so the agent's read path matches disk.
SKILL_BODY_FILENAME = "skill.md"

# Bucket id for general builtin skills not owned by an integration
# (create-artifacts, task-management, …). NOT a registered subagent: it maps to
# itself and materializes under /workspace/skills/, not /workspace/integrations/.
EXECUTOR_SUBAGENT_ID = "executor"

# User-facing label for the executor target in the skills UI. The executor is
# the general assistant (not a registered integration), so it needs an
# explicit display name where subagents get theirs from the subagent registry.
EXECUTOR_TARGET_LABEL = "General assistant"

# Builtin SKILL.md library location, relative to the app/agents/ package dir.
SKILLS_PACKAGE_DIRNAME = "skills"
BUILTIN_SKILLS_DIRNAME = "builtin"

# --- SKILL.md frontmatter parsing -------------------------------------------
# Input is a trusted, bounded builtin frontmatter block, never user-supplied,
# so the lazy `.*?` cannot be driven into pathological backtracking.
SKILL_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)  # NOSONAR python:S5852
# Forgiving YAML reader avoiding a PyYAML dependency in this hot path. The
# leading-whitespace gap is matched possessively (`\s*+`) to stay linear;
# trailing whitespace is stripped by the caller.
SKILL_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_]\w*):\s*+(.+)$")
