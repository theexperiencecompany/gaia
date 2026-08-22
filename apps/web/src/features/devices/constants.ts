/** The CLI that runs the bridge daemon on a user's machine (`packages/cli`). */
export const BRIDGE_CLI_NAME = "gaia";

/**
 * Guided wizard: pairs the machine if it isn't paired yet, then connects a
 * local MCP server or folder. The single entry point users are pointed at.
 */
export const BRIDGE_ADD_COMMAND = "gaia bridge add";

/** Holds the tunnel open so GAIA can reach the configured servers. */
export const BRIDGE_UP_COMMAND = "gaia bridge up";

/**
 * The daemon prints its pairing code as two groups of four, e.g. "ABCD-2345".
 * Mirrors USER_CODE_LENGTH in `apps/api/app/constants/device_bridge.py`.
 */
export const PAIRING_CODE_LENGTH = 8;
export const PAIRING_CODE_GROUP_LENGTH = PAIRING_CODE_LENGTH / 2;
export const PAIRING_CODE_SEPARATOR = "-";

/**
 * Accepts only the characters the API draws codes from — its alphabet omits
 * I, O, 0 and 1 so they can't be misread off a terminal.
 * Mirrors USER_CODE_ALPHABET in `apps/api/app/constants/device_bridge.py`.
 */
export const PAIRING_CODE_PATTERN = "^[A-HJ-NP-Za-hj-np-z2-9]*$";
