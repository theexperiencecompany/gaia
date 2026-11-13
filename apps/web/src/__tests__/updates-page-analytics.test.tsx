// @vitest-environment jsdom
/** Opening the Updates page is one view event, however often its feed refetches. */

import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const track = vi.fn();
const setHeader = vi.fn();

vi.mock("@/lib/analytics", () => ({
  track: (...args: unknown[]) => track(...args),
}));

vi.mock("@/hooks/layout/useHeader", () => ({
  useHeader: () => ({ setHeader }),
}));

vi.mock("@/features/updates/hooks/useMarkUpdatesSeen", () => ({
  useMarkUpdatesSeen: vi.fn(),
}));

vi.mock("@/features/updates/components/UpdatesFeed", () => ({
  UpdatesFeed: () => <div>feed</div>,
}));

vi.mock("@/components/layout/headers/UpdatesHeader", () => ({
  default: () => <div>header</div>,
}));

vi.mock("@/features/notification/components/NotificationConnectBanner", () => ({
  NotificationConnectBanner: () => null,
}));

import UpdatesPage from "@/app/[locale]/(main)/updates/page";

describe("the Updates page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reports one view when the user opens it", () => {
    const { rerender } = render(<UpdatesPage />);
    rerender(<UpdatesPage />);

    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith("delivery:updates_viewed", {});
  });
});
