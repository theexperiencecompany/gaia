class StreamStateManager {
  private streamInProgress = false;
  private conversationId: string | null = null;

  startStream(conversationId: string | null) {
    this.streamInProgress = true;
    this.conversationId = conversationId;
  }

  endStream() {
    this.streamInProgress = false;
    this.conversationId = null;
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

  updateStreamConversationId(conversationId: string) {
    if (this.streamInProgress) {
      this.conversationId = conversationId;
    }
  }
}

export const streamState = new StreamStateManager();
