# Vulture whitelist — suppress GENUINE false positives only.
#
# This file is passed to vulture as an extra source. Each name written here
# counts as a "use", suppressing the corresponding dead-code finding elsewhere.
#
# ─────────────────────────────────────────────────────────────────────────
# WHEN to add an entry — ALL of these must be true:
#   1. The symbol IS referenced, but through a mechanism vulture cannot see:
#        - dynamic dispatch: getattr / registries / Composio tool lookup by name
#        - framework-by-convention: Pydantic model fields, FastAPI `Depends`,
#          @field_validator, pytest fixtures, callback signatures
#        - string-only type annotations (e.g. `record: "Record"`)
#        - side-effect-only imports (modules imported purely to register hooks)
#   2. Removing the entry produces a REAL finding at the enforced confidence
#      (the gate runs `--min-confidence 70`). If it doesn't, the entry is inert
#      noise — do not add it.
#   3. You add a one-line comment naming the live referent / mechanism.
#
# NEVER add an entry to silence a real finding. If nothing references a symbol,
# delete the symbol. "Might need it later" is not a reason to whitelist.
#
# Keep this file honest: an entry with no live referent is dead weight and
# should be removed. Every entry below was verified to suppress a REAL conf-70
# finding (remove it and the finding returns).
# ─────────────────────────────────────────────────────────────────────────
#
# type: ignore  # vulture uses `_` as a placeholder; mypy should not type this file.

# Composio hook modules — imported in app/utils/composio_hooks/all_hooks.py purely
# for their decorator side effects (each module registers its hooks on import).
# The names are never referenced after import, but removing them breaks
# hook registration. (Side-effect-only imports.)
gmail_hooks  # noqa
reddit_hooks  # noqa
slack_hooks  # noqa
twitter_hooks  # noqa
user_id_hooks  # noqa

# LiveKit fires participant_metadata_changed(participant, old_md, new_md); the
# callback in apps/voice-agent/src/worker.py must keep the positional `old_md`
# even though it doesn't read it. (Framework callback signature.)
old_md  # noqa

# loguru `Record` is imported under TYPE_CHECKING in libs/shared/py/logging.py and
# used only inside a string annotation (record: "Record"), which vulture can't
# see. (String-only type annotation.)
Record  # noqa
