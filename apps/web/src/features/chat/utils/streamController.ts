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
let saveCallback: (() => Promise<void>) | null = null;

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
   * IMPORTANT: This is now async to properly await the save callback.
   * Returns true if a stream was aborted.
   */
  abort: async (): Promise<boolean> => {
    if (currentAbortController) {
      wasManuallyAborted = true;

      // CRITICAL: Await save callback BEFORE aborting to ensure data is persisted
      await streamController.triggerSave();

      currentAbortController.abort();
      currentAbortController = null;

      // Notify backend to cancel the stream
      if (currentStreamId) {
        cancelStreamOnBackend(currentStreamId);
        currentStreamId = null;
      }

      // Clear streaming indicator immediately
      useChatStore.getState().setStreamingConversationId(null);

      // Schedule sync after backend has time to save with exponential backoff.
      // When user clicks Stop:
      //   1. Frontend aborts HTTP connection immediately
      //   2. Backend receives cancel signal via Redis
      //   3. Backend's finally block saves to MongoDB (may take 1-5s under load)
      //   4. We retry with exponential backoff to ensure data is fully persisted
      // This ensures IndexedDB has the complete response after refresh.
      const conversationId = useChatStore.getState().activeConversationId;
      if (conversationId) {
        syncWithRetry(conversationId);
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
   * The callback should be async and will be awaited during abort.
   */
  setSaveCallback: (callback: (() => Promise<void>) | null) => {
    saveCallback = callback;
  },

  /**
   * Trigger the save callback (called before abort).
   * Now properly async and returns a Promise.
   */
  triggerSave: async (): Promise<void> => {
    if (saveCallback) {
      try {
        await saveCallback();
      } catch (error) {
        console.error("Error in save callback:", error);
      }
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
 * Sync conversation with exponential backoff retry.
 * Handles cases where backend save takes longer than expected under load.
 */
async function syncWithRetry(
  conversationId: string,
  maxRetries = 3,
  baseDelayMs = 3000,
): Promise<void> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const delay = baseDelayMs * 2 ** attempt; // 3s, 6s, 12s

    await new Promise((resolve) => setTimeout(resolve, delay));

    try {
      await syncSingleConversation(conversationId);
      // If sync succeeds, we're done
      return;
    } catch (error) {
      console.debug(
        `[syncWithRetry] Attempt ${attempt + 1}/${maxRetries} failed:`,
        error,
      );
      // Continue to next retry
    }
  }

  // Final attempt failed - log but don't throw
  console.warn(
    `[syncWithRetry] All ${maxRetries} attempts failed for conversation ${conversationId}`,
  );
}

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
