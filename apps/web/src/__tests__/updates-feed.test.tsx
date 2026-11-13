// @vitest-environment jsdom
/**
 * The Updates feed as a user reads it: what GAIA told (the message, not the facts), what it only
 * recorded, what waits, and how the next page is asked for.
 */

import type { UpdateRow, UpdatesResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const list = vi.fn();

vi.mock("@/features/updates/api/updatesApi", () => ({
  updatesApi: {
    list: (...args: unknown[]) => list(...args),
    unseen: vi.fn(),
  },
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: Record<string, unknown>) => (
    <a href={href as string} {...rest}>
      {children as ReactNode}
    </a>
  ),
}));

import { UpdatesFeed } from "@/features/updates/components/UpdatesFeed";

function row(overrides: Partial<UpdateRow> = {}): UpdateRow {
  return {
    report_id: "r1",
    subject_kind: "workflow_run",
    subject_label: "Morning briefing",
    outcome: "done",
    state: "sent",
    facts: ["Sent the briefing"],
    told: ["Your briefing is ready."],
    conversation_id: "chat-1",
    occurred_at: "2026-11-10T09:00:00Z",
    told_at: "2026-11-10T09:01:00Z",
    created_at: "2026-11-10T09:00:00Z",
    ...overrides,
  };
}

function page(
  updates: UpdateRow[],
  nextBefore: string | null = null,
): UpdatesResponse {
  return { updates, next_before: nextBefore };
}

function renderFeed(filter: Parameters<typeof UpdatesFeed>[0]["filter"]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <UpdatesFeed filter={filter} />
    </QueryClientProvider>,
  );
}

describe("UpdatesFeed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows what GAIA told the user, with the subject and a way into its conversation", async () => {
    list.mockResolvedValue(page([row()]));

    renderFeed("all");

    expect(await screen.findByText("Morning briefing")).toBeDefined();
    expect(screen.getByText("Your briefing is ready.")).toBeDefined();
    expect(screen.getByText("Workflow")).toBeDefined();
    expect(screen.getByText("Told you")).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Open" }).getAttribute("href"),
    ).toBe("/c/chat-1");
  });

  it("shows the recorded facts, not a message, for what was only kept", async () => {
    list.mockResolvedValue(
      page([
        row({
          state: "dropped",
          drop_reason: "nothing_new",
          told: null,
          facts: ["Nothing changed since Tuesday"],
          conversation_id: null,
        }),
      ]),
    );

    renderFeed("all");

    expect(
      await screen.findByText("Nothing changed since Tuesday"),
    ).toBeDefined();
    expect(screen.getByText("Nothing new")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();
  });

  it("says a held update waits", async () => {
    list.mockResolvedValue(
      page([
        row({
          state: "held",
          told: null,
          held_until: new Date(Date.now() + 3_600_000).toISOString(),
        }),
      ]),
    );

    renderFeed("held");

    expect(await screen.findByText(/^Waiting, in about 1 hour$/)).toBeDefined();
  });

  it("asks the API for the filter it is showing", async () => {
    list.mockResolvedValue(page([]));

    renderFeed("needs_you");

    await waitFor(() => expect(list).toHaveBeenCalledWith("needs_you", null));
    expect(await screen.findByText("Nothing needs you")).toBeDefined();
  });

  it("loads the next page from the cursor the last one handed back", async () => {
    list
      .mockResolvedValueOnce(page([row()], "2026-11-10T09:00:00Z"))
      .mockResolvedValueOnce(
        page([row({ report_id: "r2", subject_label: "Weekly report" })]),
      );

    renderFeed("all");
    fireEvent.click(await screen.findByText("Load more"));

    expect(await screen.findByText("Weekly report")).toBeDefined();
    expect(list).toHaveBeenLastCalledWith("all", "2026-11-10T09:00:00Z");
    expect(screen.queryByText("Load more")).toBeNull();
  });

  it("lets the user retry when the feed cannot be read", async () => {
    list.mockRejectedValueOnce(new Error("offline"));
    list.mockResolvedValueOnce(page([row()]));

    renderFeed("all");
    fireEvent.click(await screen.findByText("Try again"));

    expect(await screen.findByText("Morning briefing")).toBeDefined();
  });
});
