// @vitest-environment jsdom
// Regression: an in-app desk briefing rendered as one paragraph with literal asterisks.
import { render, screen } from "@testing-library/react";
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

import { EnhancedNotificationCard } from "@/features/notification/components/EnhancedNotificationCard";
import {
  NotificationStatus,
  type NotificationView,
} from "@/types/features/notificationTypes";

const BRIEFING =
  "Here's today's briefing.\n\nNeeds you\n- Sam: the lease, by Friday\n- Priya: **budget** sign-off\n\nFiltered\n- 7";

function briefingNotification(): NotificationView {
  return {
    id: "n1",
    user_id: "user_1",
    source: "background_job",
    type: "info",
    status: NotificationStatus.DELIVERED,
    channels: [],
    content: { title: "Inbox desk", body: BRIEFING, actions: [] },
    created_at: new Date().toISOString(),
  } as unknown as NotificationView;
}

describe("notification card body", () => {
  it("renders a briefing's items as a list and its emphasis as markup", async () => {
    render(<EnhancedNotificationCard notification={briefingNotification()} />);

    const items = await screen.findAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Sam: the lease, by Friday",
      "Priya: budget sign-off",
      "7",
    ]);
    expect(screen.getByText("budget").outerHTML).toContain(
      'data-streamdown="strong"',
    );
    expect(screen.queryByText(/\*\*budget\*\*/)).toBeNull();
  });
});
