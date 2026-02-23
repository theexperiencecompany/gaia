// Safety timeout for pendingSave flag (10 seconds)
const PENDING_SAVE_TIMEOUT_MS = 10000;

class StreamStateManager {
  private streamInProgress = false;
  private conversationId: string | null = null;
  private pendingSave = false;
  private pendingSaveTimeoutId: ReturnType<typeof setTimeout> | null = null;

  startStream(conversationId: string | null) {
    this.streamInProgress = true;
    this.conversationId = conversationId;
  }

  endStream() {
    this.streamInProgress = false;
    this.conversationId = null;
    // Note: Don't clear pendingSave here - it's managed separately
  }

  /**
   * Set pending save flag to block sync operations during save.
   * Includes a safety timeout to prevent permanent blocking if save fails.
   */
  setPendingSave(pending: boolean) {
    // Clear any existing timeout
    if (this.pendingSaveTimeoutId) {
      clearTimeout(this.pendingSaveTimeoutId);
      this.pendingSaveTimeoutId = null;
    }

    this.pendingSave = pending;

    // Set safety timeout when enabling pendingSave
    if (pending) {
      this.pendingSaveTimeoutId = setTimeout(() => {
        console.warn(
          "[streamState] pendingSave timeout - auto-clearing to prevent sync block",
        );
        this.pendingSave = false;
        this.pendingSaveTimeoutId = null;
      }, PENDING_SAVE_TIMEOUT_MS);
    }
  }

  /**
   * Check if a save operation is pending
   */
  isPendingSave(): boolean {
    return this.pendingSave;
  }

  isStreaming(): boolean {
    return this.streamInProgress;
  }

  getStreamingConversationId(): string | null {
    return this.conversationId;
  }

  isStreamingConversation(conversationId: string): boolean {
    return this.streamInProgress && this.conversationId === conversationId;
  }

  /**
   * Check if sync should be blocked for a given conversation.
   * Returns true if:
   * - A save operation is pending (after abort)
   * - The conversation is currently being streamed
   */
  shouldBlockSync(conversationId: string): boolean {
    return (
      this.pendingSave ||
      (this.streamInProgress && this.conversationId === conversationId)
    );
  }

  updateStreamConversationId(conversationId: string) {
    if (this.streamInProgress) {
      this.conversationId = conversationId;
    }
  }
}

export const streamState = new StreamStateManager();
