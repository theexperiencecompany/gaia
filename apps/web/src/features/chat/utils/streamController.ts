"use client";

/**
 * Stream Controller - Manages streaming state and cancellation.
 *
 * This module tracks the current streaming session and provides methods to:
 * - Track abort controller for HTTP connection
 * - Track stream_id for backend cancellation
 * - Call backend cancel endpoint when user clicks Stop
 * - Manage save callbacks for preserving progress
 * - Sync streaming indicator state with chatStore
 */

import { syncSingleConversation } from "@/services";
import { useChatStore } from "@/stores/chatStore";

// Module-level state
let currentAbortController: AbortController | null = null;
let currentStreamId: string | null = null;
let wasManuallyAborted = false;
let saveCallback: (() => void) | null = null;

export const streamController = {
  /**
   * Set the abort controller for the current stream.
   * Called when starting a new stream.
   */
  set: (controller: AbortController | null) => {
    currentAbortController = controller;
    wasManuallyAborted = false;
  },

  /**
   * Get the current abort controller.
   */
  get: () => currentAbortController,

  /**
   * Set the stream ID for backend cancellation.
   * Parsed from the X-Stream-Id header or first SSE event.
   */
  setStreamId: (streamId: string | null) => {
    currentStreamId = streamId;
  },

  /**
   * Get the current stream ID.
   */
  getStreamId: () => currentStreamId,

  /**
   * Abort the current stream and notify backend.
   * Returns true if a stream was aborted.
   */
  abort: () => {
    if (currentAbortController) {
      wasManuallyAborted = true;
      currentAbortController.abort();
      currentAbortController = null;

      // Notify backend to cancel the stream
      if (currentStreamId) {
        cancelStreamOnBackend(currentStreamId);
        currentStreamId = null;
      }

      // Clear streaming indicator immediately
      useChatStore.getState().setStreamingConversationId(null);

      // Schedule sync after backend has time to save.
      // When user clicks Stop:
      //   1. Frontend aborts HTTP connection immediately
      //   2. Backend receives cancel signal via Redis
      //   3. Backend's finally block saves to MongoDB (takes ~1-2s)
      //   4. We wait 3s then fetch to ensure data is fully persisted
      // This ensures IndexedDB has the complete response after refresh.
      const conversationId = useChatStore.getState().activeConversationId;
      if (conversationId) {
        setTimeout(async () => {
          await syncSingleConversation(conversationId);
        }, 3000);
      }

      return true;
    }
    return false;
  },

  /**
   * Check if the stream was manually aborted by user.
   */
  wasAborted: () => wasManuallyAborted,

  /**
   * Set a callback to save progress before aborting.
   */
  setSaveCallback: (callback: (() => void) | null) => {
    saveCallback = callback;
  },

  /**
   * Trigger the save callback (called before abort).
   */
  triggerSave: () => {
    if (saveCallback) {
      saveCallback();
    }
  },

  /**
   * Clear all state (also clears streaming indicator).
   */
  clear: () => {
    currentAbortController = null;
    currentStreamId = null;
    wasManuallyAborted = false;
    saveCallback = null;

    // Ensure streaming indicator is cleared
    useChatStore.getState().setStreamingConversationId(null);
  },
};

/**
 * Call the backend cancel endpoint.
 * Fire-and-forget - we don't wait for response.
 */
async function cancelStreamOnBackend(streamId: string): Promise<void> {
  try {
    await fetch(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}cancel-stream/${streamId}`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  } catch (error) {
    // Silently ignore cancel errors - the stream might already be done
    console.debug("Cancel stream request failed:", error);
  }
}
