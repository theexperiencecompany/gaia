// @vitest-environment jsdom
/** The owner opening their own link gets its share settings in the page chrome; nobody else does. */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openLinkInBrowser = vi.hoisted(() => vi.fn());
vi.mock("@/features/short-links/api/linkViewerApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/short-links/api/linkViewerApi")
  >()),
  openLinkInBrowser,
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));
vi.mock("@/features/chat/components/interface/RichContentRenderer", () => ({
  RichContentRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("@/features/short-links/components/ShareLinkControls", () => ({
  ShareLinkControls: ({
    target,
    stopWarning,
  }: {
    target: LinkTarget;
    stopWarning?: string;
  }) => (
    <span data-testid="share" data-warning={stopWarning ?? ""}>
      {"id" in target
        ? `${target.type}:${target.id}`
        : `${target.type}:${target.conversation_id}:${target.path}`}
    </span>
  ),
}));

import { BRIEF_STOP_WARNING } from "@/features/briefing";
import { OpenLinkView } from "@/features/short-links/components/OpenLinkView";
import { PublicLinkView } from "@/features/short-links/components/PublicLinkView";
import type { LinkEnvelope, LinkTarget } from "@/types/features/shortLinkTypes";

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
    owner_target: isOwner ? { type: "todo_deliverable", id: "todo-123" } : null,
  };
}

describe("PublicLinkView chrome", () => {
  it("shows the owner the link's share controls for its own target", () => {
    render(<PublicLinkView slug="abcdefghijk" envelope={envelope(true)} />);

    expect(screen.getByTestId("share").textContent).toBe(
      "todo_deliverable:todo-123",
    );
  });

  it("warns the owner of a brief what stopping cannot take back", () => {
    const brief: LinkEnvelope = {
      ...envelope(true),
      target_type: "briefing",
      owner_target: { type: "briefing", id: "brief-1" },
      view: {
        target_type: "briefing",
        kind: "daily",
        edition_image_url: null,
        payload: {
          kicker: "Friday",
          date: "Nov 13",
          headline: "A clear Friday",
          lede: "",
          stats: [],
          sections: [],
          mood: "clear",
          caption: "",
          hue: 0,
          calendar: [],
        },
      },
    };
    render(<PublicLinkView slug="abcdefghijk" envelope={brief} />);

    expect(screen.getByTestId("share").dataset.warning).toBe(
      BRIEF_STOP_WARNING,
    );
  });

  it("shows a recipient no share controls", () => {
    render(<PublicLinkView slug="abcdefghijk" envelope={envelope(false)} />);

    expect(screen.queryByTestId("share")).toBeNull();
    expect(screen.getByRole("button", { name: "Report" })).toBeTruthy();
  });
});

describe("OpenLinkView", () => {
  beforeEach(() => {
    openLinkInBrowser.mockReset();
  });

  it("gives the owner the share controls once their browser reads the link", async () => {
    openLinkInBrowser.mockResolvedValue(envelope(true));

    render(<OpenLinkView slug="abcdefghijk" envelope={envelope(false)} />);

    await waitFor(() =>
      expect(screen.getByTestId("share").textContent).toBe(
        "todo_deliverable:todo-123",
      ),
    );
    expect(openLinkInBrowser).toHaveBeenCalledWith("abcdefghijk");
  });

  it("keeps the server's view for a reader who is not the owner", async () => {
    openLinkInBrowser.mockResolvedValue(envelope(false));

    render(<OpenLinkView slug="abcdefghijk" envelope={envelope(false)} />);

    await waitFor(() => expect(openLinkInBrowser).toHaveBeenCalled());
    expect(screen.queryByTestId("share")).toBeNull();
    expect(screen.getByText("Trip plan")).toBeTruthy();
  });
});
