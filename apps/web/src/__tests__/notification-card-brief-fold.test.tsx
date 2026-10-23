// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {},
}));

vi.mock("@/components/shared/ConfirmationDialog", () => ({
  ConfirmationDialog: () => null,
}));

const fetchBriefing = vi.fn();
vi.mock("@/features/briefing/api/briefingApi", () => ({
  briefingApi: { fetchBriefing: (id: string) => fetchBriefing(id) },
}));

import { NotificationCard } from "@/features/notification/components/NotificationCard";
import {
  NotificationStatus,
  type NotificationView,
} from "@/types/features/notificationTypes";

const HEADLINE = "Three decisions are waiting on you";
const MESSAGE = "The Acme renewal needs your sign-off today.";

function notification(metadata: Record<string, unknown>): NotificationView {
  return {
    id: "n1",
    user_id: "user_1",
    source: "background_job",
    type: "info",
    status: NotificationStatus.DELIVERED,
    channels: [],
    content: { title: HEADLINE, body: MESSAGE, actions: [] },
    metadata,
    created_at: new Date().toISOString(),
  } as unknown as NotificationView;
}

function renderCard(view: NotificationView) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NotificationCard notification={view} />
    </QueryClientProvider>,
  );
}

describe("briefing notification", () => {
  it("folds the brief and opens it, loaded by id, as a letter", async () => {
    fetchBriefing.mockResolvedValue({
      id: "brief_1",
      date: "2026-10-22",
      edition_image_url: null,
      payload: {
        kicker: "THE MORNING BRIEF",
        date: "2026-10-22",
        headline: HEADLINE,
        lede: "",
        caption: "",
        message: MESSAGE,
        stats: [],
        sections: [
          {
            numeral: "I",
            title: "Needs you",
            items: [{ text: "Approve the Acme MSA" }],
          },
        ],
      },
    });
    renderCard(
      notification({
        briefing_id: "brief_1",
        date: "2026-10-22",
        edition_image_url: null,
      }),
    );

    expect(screen.queryByText(MESSAGE)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: `Open brief: ${HEADLINE}` }),
    );

    expect(await screen.findByText("Approve the Acme MSA")).toBeTruthy();
    expect(screen.getByText(MESSAGE)).toBeTruthy();
    expect(fetchBriefing).toHaveBeenCalledWith("brief_1");
  });

  it("unfolds a rendered edition on its own, with none of the brief's text below it", async () => {
    // jsdom never decodes images nor cuts bitmaps; the browser does both off this path.
    Object.defineProperty(HTMLImageElement.prototype, "decode", {
      configurable: true,
      value: () => Promise.resolve(),
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: () => undefined,
      fillRect: () => undefined,
      getImageData: (
        _x: number,
        _y: number,
        width: number,
        height: number,
      ) => ({
        data: new Uint8ClampedArray(width * height * 4).fill(236),
      }),
    } as unknown as CanvasRenderingContext2D);
    vi.stubGlobal("createImageBitmap", () =>
      Promise.resolve({ width: 540, height: 500, close: () => undefined }),
    );
    vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(
      1620,
    );
    vi.spyOn(
      HTMLImageElement.prototype,
      "naturalHeight",
      "get",
    ).mockReturnValue(4500);
    fetchBriefing.mockResolvedValue({
      id: "brief_2",
      date: "2026-10-22",
      edition_image_url: "https://cdn.example/edition.png",
      payload: {
        kicker: "THE MORNING BRIEF",
        date: "2026-10-22",
        headline: HEADLINE,
        lede: "",
        caption: "",
        message: MESSAGE,
        stats: [],
        sections: [],
      },
    });
    renderCard(
      notification({
        briefing_id: "brief_2",
        date: "2026-10-22",
        edition_image_url: "https://cdn.example/edition.png",
      }),
    );

    fireEvent.click(
      screen.getByRole("button", { name: `Open brief: ${HEADLINE}` }),
    );

    expect(await screen.findByRole("img", { name: HEADLINE })).toBeTruthy();
    expect(screen.queryByText(MESSAGE)).toBeNull();
    expect(fetchBriefing).toHaveBeenCalledWith("brief_2");
  });

  it("leaves any other notification's body as it was", () => {
    renderCard(notification({}));

    expect(screen.getByText(MESSAGE)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Open brief:/ })).toBeNull();
  });
});
