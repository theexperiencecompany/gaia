// @vitest-environment jsdom
// Regression: an email notification's "Review" action did nothing in chat,
// because the chat list never hosted the email-preview modal.
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

vi.mock("@/features/mail/components/EmailPreviewModal", () => ({
  EmailPreviewModal: ({ subject }: { subject: string }) => (
    <div role="dialog">{subject}</div>
  ),
}));

import NotificationListSection from "@/features/chat/components/bubbles/bot/NotificationListSection";
import {
  ActionType,
  NotificationStatus,
  type NotificationView,
} from "@/types/features/notificationTypes";

function emailDraftNotification(): NotificationView {
  return {
    id: "n1",
    user_id: "user_1",
    source: "background_job",
    type: "info",
    status: NotificationStatus.DELIVERED,
    channels: [],
    content: {
      title: "Draft ready",
      body: "A reply is drafted.",
      actions: [
        {
          id: "a1",
          label: "Review draft",
          type: ActionType.MODAL,
          config: {
            modal: {
              component: "EmailPreviewModal",
              props: { subject: "Re: lease", body: "Hi", recipients: [] },
            },
          },
        },
      ],
    },
    created_at: new Date().toISOString(),
  } as unknown as NotificationView;
}

describe("chat notification list", () => {
  it("opens the email preview when a modal action is pressed", async () => {
    render(
      <NotificationListSection notifications={[emailDraftNotification()]} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Review draft" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toBe("Re: lease");
  });
});
