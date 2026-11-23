// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/features/workflows/components/WorkflowModal", () => ({
  default: () => null,
}));

import WorkflowDraftCard from "@/features/workflows/components/WorkflowDraftCard";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";

const BILLING = "The email is from a customer and is about billing";

describe("a drafted runs-only-when condition", () => {
  it("is shown on the draft card", () => {
    const draft: WorkflowDraftData = {
      suggested_title: "Billing replies",
      suggested_description: "Drafts a reply to customer billing emails",
      prompt: "Draft a reply",
      trigger_type: "integration",
      trigger_slug: "GMAIL_NEW_GMAIL_MESSAGE",
      runs_only_when: BILLING,
    };

    render(<WorkflowDraftCard draft={draft} />);

    expect(screen.getByText(`Runs only when: ${BILLING}`)).toBeTruthy();
  });
});
