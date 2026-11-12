// @vitest-environment jsdom
/** The owner opening their own link gets its share settings in the page chrome; nobody else does. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));
vi.mock("@/features/chat/components/interface/RichContentRenderer", () => ({
  RichContentRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("@/features/short-links/components/ShareLinkControls", () => ({
  ShareLinkControls: ({
    targetType,
    targetId,
  }: {
    targetType: string;
    targetId: string;
  }) => <span data-testid="share">{`${targetType}:${targetId}`}</span>,
}));

import { PublicLinkView } from "@/features/short-links/components/PublicLinkView";
import type { LinkEnvelope } from "@/types/features/shortLinkTypes";

function envelope(isOwner: boolean): LinkEnvelope {
  return {
    access: "people",
    target_type: "todo_deliverable",
    view: {
      target_type: "todo_deliverable",
      title: "Trip plan",
      completed: false,
      content: "Day one",
    },
    content: null,
    downloadable: false,
    is_owner: isOwner,
    owner_target_id: isOwner ? "todo-123" : null,
  };
}

describe("PublicLinkView chrome", () => {
  it("shows the owner the link's share controls for its own target", () => {
    render(<PublicLinkView slug="abcdefghijk" envelope={envelope(true)} />);

    expect(screen.getByTestId("share").textContent).toBe(
      "todo_deliverable:todo-123",
    );
  });

  it("shows a recipient no share controls", () => {
    render(<PublicLinkView slug="abcdefghijk" envelope={envelope(false)} />);

    expect(screen.queryByTestId("share")).toBeNull();
    expect(screen.getByRole("button", { name: "Report" })).toBeTruthy();
  });
});
