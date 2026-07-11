/** The CLI that runs the bridge daemon on a user's machine (`apps/bridge`). */
export const BRIDGE_CLI_NAME = "gaia";

/**
 * Guided wizard: pairs the machine if it isn't paired yet, then connects a
 * local MCP server or folder. The single entry point users are pointed at.
 */
export const BRIDGE_ADD_COMMAND = "gaia bridge add";

/** Holds the tunnel open so GAIA can reach the configured servers. */
export const BRIDGE_UP_COMMAND = "gaia bridge up";

/** Shape of the pairing code the daemon prints, used as the input placeholder. */
export const PAIRING_CODE_PLACEHOLDER = "ABCD-2345";
