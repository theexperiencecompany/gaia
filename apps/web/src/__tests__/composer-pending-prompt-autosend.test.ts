/**
 * The `pendingPrompt` auto-send flag.
 *
 * ChatPage branches on this to decide between filling the composer and sending
 * the message as the user's own turn, so a flag that leaked across prompts
 * would silently auto-send someone's next drafted text.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { useComposerStore } from "@/stores/composerStore";

const store = () => useComposerStore.getState();

describe("composerStore pendingPrompt auto-send", () => {
  beforeEach(() => {
    store().clearPendingPrompt();
  });

  it("defaults to filling the composer, not sending", () => {
    store().setPendingPrompt("draft this");
    expect(store().pendingPrompt).toBe("draft this");
    expect(store().pendingPromptAutoSend).toBe(false);
  });

  it("marks a prompt for auto-send when asked", () => {
    store().setPendingPrompt("Hi! I'm a founder. Who are you?", true);
    expect(store().pendingPromptAutoSend).toBe(true);
  });

  it("clears the flag with the prompt", () => {
    store().setPendingPrompt("Hi!", true);
    store().clearPendingPrompt();
    expect(store().pendingPrompt).toBeNull();
    expect(store().pendingPromptAutoSend).toBe(false);
  });

  it("does not carry the flag onto the next prompt", () => {
    store().setPendingPrompt("Hi!", true);
    store().setPendingPrompt("something else");
    expect(store().pendingPromptAutoSend).toBe(false);
  });

  it("never auto-sends a prompt routed through appendToInput", () => {
    store().setPendingPrompt("Hi!", true);
    store().appendToInput("summarise this page");
    expect(store().pendingPromptAutoSend).toBe(false);
  });
});
