// @vitest-environment jsdom
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MentionEditor } from "@/features/integrations/components/MentionEditor";

const SAVED_PROMPT = "Run the sweep2 scripted check.";

/**
 * Reproduces the workflow edit-modal sequence that wiped saved prompts.
 *
 * The modal mounts empty, then an effect resets to the saved prompt; Tiptap's
 * async instance (`immediatelyRender: false`) still captures the stale empty
 * `content` from mount, and its `setEditable` lifecycle effect emits an
 * 'update' carrying that stale doc — forwarded through onChange, it clobbers
 * the restored prompt and the value-sync effect erases the visible text too.
 */
describe("MentionEditor external value reset", () => {
  it("does not report lifecycle emissions as user edits", async () => {
    const onChange = vi.fn();
    const { container, rerender } = render(
      <MentionEditor value="" onChange={onChange} toolNames={[]} />,
    );

    rerender(
      <MentionEditor value={SAVED_PROMPT} onChange={onChange} toolNames={[]} />,
    );

    await waitFor(() => {
      expect(container.querySelector(".ProseMirror")).toBeTruthy();
    });
    await waitFor(() => {
      expect(container.querySelector(".ProseMirror")?.textContent).toBe(
        SAVED_PROMPT,
      );
    });

    // The stale initial doc must never be reported as an edit — doing so
    // clobbers the externally-set value (the saved workflow prompt).
    expect(onChange).not.toHaveBeenCalledWith("");
    expect(onChange).not.toHaveBeenCalled();
  });
});
