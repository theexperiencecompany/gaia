// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MotionGlobalConfig } from "motion/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

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

const OPEN_BRIEFING = {
  id: "open",
  type: "redirect",
  label: "Open briefing",
  style: "primary",
  config: {
    redirect: {
      url: "/brief/brief_1",
      open_in_new_tab: false,
      close_notification: true,
    },
  },
};

function notification(
  metadata: Record<string, unknown>,
  actions: unknown[] = [],
): NotificationView {
  return {
    id: "n1",
    user_id: "user_1",
    source: "background_job",
    type: "info",
    status: NotificationStatus.DELIVERED,
    channels: [],
    content: { title: HEADLINE, body: MESSAGE, actions },
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
  // The letter's unfold and exit run on timers jsdom does not keep in step; settle them at once.
  beforeAll(() => {
    MotionGlobalConfig.skipAnimations = true;
  });
  afterAll(() => {
    MotionGlobalConfig.skipAnimations = false;
  });

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

  it("opens the brief from the card alone, without a second button to the same brief", () => {
    renderCard(notification({ briefing_id: "brief_1" }, [OPEN_BRIEFING]));

    expect(
      screen.getByRole("button", { name: `Open brief: ${HEADLINE}` }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open briefing" })).toBeNull();
  });

  it("closes the opened brief from its close button", async () => {
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
        sections: [],
      },
    });
    renderCard(notification({ briefing_id: "brief_1" }));

    fireEvent.click(
      screen.getByRole("button", { name: `Open brief: ${HEADLINE}` }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps an action that goes somewhere other than the brief", () => {
    renderCard(notification({}, [OPEN_BRIEFING]));

    expect(screen.getByRole("button", { name: "Open briefing" })).toBeTruthy();
  });

  it("leaves any other notification's body as it was", () => {
    renderCard(notification({}));

    expect(screen.getByText(MESSAGE)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Open brief:/ })).toBeNull();
  });
});
