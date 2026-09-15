// @vitest-environment jsdom
/**
 * The one thing the section has to actually do: reorder where GAIA texts you first.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchPriority = vi.fn();
const updatePriority = vi.fn();

vi.mock("@/features/settings/api/chatChannelApi", () => ({
  chatChannelApi: {
    fetchPriority: () => fetchPriority(),
    updatePriority: (order: string[]) => updatePriority(order),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import type { NotificationPlatform } from "@/features/notification/constants";
import { ChatChannelSettings } from "@/features/settings/components/ChatChannelSettings";

const linked: NotificationPlatform[] = ["telegram", "whatsapp"];

describe("ChatChannelSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchPriority.mockResolvedValue({ priority: ["telegram", "whatsapp"] });
    updatePriority.mockImplementation((priority: string[]) =>
      Promise.resolve({ priority }),
    );
  });

  it("promotes the second platform and saves the new order", async () => {
    render(<ChatChannelSettings linkedPlatforms={linked} />);
    await waitFor(() =>
      expect(screen.getByText("Texts you here first")).toBeDefined(),
    );

    fireEvent.click(screen.getByLabelText("Move WhatsApp up"));

    await waitFor(() =>
      expect(updatePriority).toHaveBeenCalledWith(["whatsapp", "telegram"]),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Move WhatsApp up")).toHaveProperty(
        "disabled",
        true,
      ),
    );
  });
});
