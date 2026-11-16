/**
 * The "Thinking..." placeholder a streamed reply fills in.
 *
 * It is posted alongside the chat request rather than ahead of it, so the request never queues
 * behind a platform round-trip. That ordering means a placeholder can fail after the request has
 * started doing the user's work, so its failure must never strand the reply: an edit aimed at
 * it is told the message is gone, which the streamer answers by opening a new message.
 */
import { PlaceholderUnavailableError } from "./delivery-errors";

export class ReplyPlaceholder<Id> {
  private readonly placeholderId: Promise<Id | null>;
  /** Set once the reply opens a message of its own; edits land there from then on. */
  private replyId: Id | undefined;

  /**
   * @param post - Posts the placeholder and resolves to its id; called immediately.
   * @param onPostFailed - Records why it could not be posted. The turn goes on without it.
   */
  constructor(post: () => Promise<Id>, onPostFailed: (error: unknown) => void) {
    this.placeholderId = post().catch((error: unknown) => {
      onPostFailed(error);
      return null;
    });
  }

  /** The placeholder's id once posted, or null when it could not be. */
  posted(): Promise<Id | null> {
    return this.placeholderId;
  }

  /** Points later edits at a message the reply opened. */
  moveTo(id: Id): void {
    this.replyId = id;
  }

  /**
   * The message an edit lands on: the reply's own latest message, else the placeholder.
   * Rejects with a message-gone error when there is neither.
   */
  async current(): Promise<Id> {
    if (this.replyId !== undefined) return this.replyId;
    const placeholderId = await this.placeholderId;
    if (placeholderId === null) throw new PlaceholderUnavailableError();
    return placeholderId;
  }
}
