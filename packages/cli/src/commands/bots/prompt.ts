/**
 * The credential `gaia bots add` asks for, shared by its flow and its screen.
 * @module commands/bots/prompt
 */

/** The input the screen answers with a pasted credential. */
export const BOT_CREDENTIAL_INPUT = "bot_credential";

export interface CredentialRequest {
  label: string;
  /** Where to find it; shown the first time only. */
  hint?: string;
  /** Why the last paste was refused and how many tries are left. */
  retry?: string;
}
