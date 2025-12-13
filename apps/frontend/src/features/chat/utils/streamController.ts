"use client";

// Simple module-level storage for the current abort controller
let currentAbortController: AbortController | null = null;
let wasManuallyAborted = false;
let saveCallback: (() => void) | null = null;

export const streamController = {
  set: (controller: AbortController | null) => {
    currentAbortController = controller;
    wasManuallyAborted = false; // Reset flag when new controller is set
  },

  get: () => currentAbortController,

  abort: () => {
    if (currentAbortController) {
      wasManuallyAborted = true; // Set flag when manually aborted
      currentAbortController.abort();
      currentAbortController = null;
      return true;
    }
    return false;
  },

  wasAborted: () => wasManuallyAborted,

  setSaveCallback: (callback: (() => void) | null) => {
    saveCallback = callback;
  },

  triggerSave: () => {
    if (saveCallback) {
      saveCallback();
    }
  },

  clear: () => {
    currentAbortController = null;
    wasManuallyAborted = false; // Reset flag when cleared
    saveCallback = null; // Clear save callback
  },
};
