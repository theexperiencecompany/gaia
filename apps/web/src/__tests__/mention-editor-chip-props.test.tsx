// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MentionEditor } from "@/features/integrations/components/MentionEditor";

/**
 * The mention chip is a Tiptap node view, rendered through Tiptap's portals
 * rather than as a child of MentionEditor. The editor's chip props (icon,
 * removable) must still reach it.
 */
describe("MentionEditor chip props", () => {
  it("renders an inserted mention with the editor's icon and remove control", async () => {
    render(
      <MentionEditor
        value="Use @gmail today"
        onChange={vi.fn()}
        toolNames={["gmail"]}
        renderMentionIcon={(name) => <span data-testid={`icon-${name}`} />}
        mentionRemovable
      />,
    );

    expect(await screen.findByTestId("icon-gmail")).toBeTruthy();
    expect(screen.getByRole("button", { name: "close chip" })).toBeTruthy();
  });
});
