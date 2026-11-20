import { ApiError } from "../api/apiError";

const HTTP_CONFLICT = 409;

/** The code the API answers a create with when the client-minted conversation id is another user's. */
export const CONVERSATION_ID_TAKEN = "conversation_id_taken";

/** Whether a send was refused because the conversation id this client minted already belongs to someone else. */
export function isConversationIdTaken(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === HTTP_CONFLICT &&
    error.envelope?.code === CONVERSATION_ID_TAKEN
  );
}
