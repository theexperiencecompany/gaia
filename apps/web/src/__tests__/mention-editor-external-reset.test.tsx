// @vitest-environment jsdom
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MentionEditor } from "@/features/integrations/components/MentionEditor";

const SAVED_PROMPT = "Run the sweep2 scripted check.";

/**
 * Reproduces the workflow edit-modal sequence that wiped saved prompts:
 *
 * 1. The modal mounts the form with react-hook-form defaults (`value=""`).
 * 2. An effect resets the form to the saved workflow prompt right after mount.
 * 3. Meanwhile Tiptap creates its instance asynchronously
 *    (`immediatelyRender: false`) with `content` captured from step 1 — a
 *    stale empty document.
 * 4. When the instance appears, the `setEditable` lifecycle effect ran and
 *    Tiptap emits an 'update' for it by default, carrying that stale doc.
 * 5. Forwarding the emission through onChange clobbered the restored prompt
 *    with "" — and the value-sync effect then erased the visible text too,
 *    leaving Save permanently disabled.
 */
describe("MentionEditor external value reset", () => {
  it("does not report lifecycle emissions as user edits", async () => {
    const onChange = vi.fn();
    const { container, rerender } = render(
      <MentionEditor value="" onChange={onChange} toolNames={[]} />,
    );

    // Step 2: the form value arrives right after mount (modal init effect).
    rerender(
      <MentionEditor value={SAVED_PROMPT} onChange={onChange} toolNames={[]} />,
    );

    // Steps 3-4: the editor instance appears and settles.
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
