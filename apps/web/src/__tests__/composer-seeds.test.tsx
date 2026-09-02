// @vitest-environment jsdom
/**
 * The two out-of-band ways text lands in the composer: a prompt staged in the
 * store (fill mode) and a `?q=` deep link. Both must seed exactly once — a
 * StrictMode double effect that appended twice would hand the user a
 * duplicated draft — and neither may touch an auto-send prompt, which is the
 * user's turn and belongs to the page's sender.
 */
import { render } from "@testing-library/react";
import { StrictMode, useRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

import { useComposerSeeds } from "@/features/chat/hooks/useComposerSeeds";
import { useComposerStore } from "@/stores/composerStore";

function Harness() {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  useComposerSeeds(inputRef);
  return <textarea ref={inputRef} />;
}

const store = () => useComposerStore.getState();

describe("useComposerSeeds", () => {
  beforeEach(() => {
    replace.mockClear();
    store().clearPendingPrompt();
    store().clearInputText();
    window.history.replaceState({}, "", "/c");
  });

  it("fills the composer once from a staged prompt and clears the stage", () => {
    store().setPendingPrompt("draft this");

    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    expect(store().inputText).toBe("draft this");
    expect(store().pendingPrompt).toBeNull();
  });

  it("leaves an auto-send prompt alone — that is the page's turn to send", () => {
    store().setPendingPrompt("Hi! I'm a founder. Who are you?", true);

    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    expect(store().inputText).toBe("");
    expect(store().pendingPrompt).toBe("Hi! I'm a founder. Who are you?");
  });

  it("seeds a ?q= deep link once and strips the param from the URL", () => {
    window.history.replaceState({}, "", "/c?q=summarise%20my%20inbox&tab=x");

    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    expect(store().inputText).toBe("summarise my inbox");
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/c?tab=x", { scroll: false });
  });

  it("does nothing without a seed", () => {
    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    expect(store().inputText).toBe("");
    expect(replace).not.toHaveBeenCalled();
  });
});
