/**
 * The user's standing instructions, shared by web and mobile so neither drifts
 * from the API (apps/api/app/models/user_instructions_models.py and
 * apps/api/app/constants/error_codes.py).
 */

/** The scope GAIA follows in every conversation; any other scope is an integration id. */
export const GLOBAL_INSTRUCTIONS_SCOPE = "global";

/** Server-enforced length limit for every scope. */
export const MAX_INSTRUCTIONS_CHARS = 8000;

/** ErrorEnvelope code for a save whose base_revision is no longer current. */
export const INSTRUCTIONS_CONFLICT_CODE = "INSTRUCTIONS_CONFLICT";
