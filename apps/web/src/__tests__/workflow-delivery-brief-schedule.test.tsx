// @vitest-environment jsdom
import { WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import type { BriefingSchedule } from "@gaia/shared/types";
import type { WorkflowDelivery } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkflowDeliveryField from "@/features/workflows/components/workflow-modal/WorkflowDeliveryField";
import { NotificationsAPI } from "@/services/api/notifications";

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getBriefingSchedule: vi.fn(),
    updateBriefingSchedule: vi.fn(),
  },
}));

function renderField(schedule: BriefingSchedule, value: WorkflowDelivery) {
  vi.mocked(NotificationsAPI.getBriefingSchedule).mockResolvedValue(schedule);
  return render(<WorkflowDeliveryField value={value} onChange={vi.fn()} />);
}

const briefButton = () =>
  screen.getByRole("button", { name: "Add to my brief" });

describe("adding a workflow's results to the brief", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is offered against the next daily brief while daily briefs are on", async () => {
    renderField({ frequency: "weekdays", hour: 8 }, "brief");

    expect(
      await screen.findByText("Results wait for your next daily brief."),
    ).toBeTruthy();
    expect(briefButton().hasAttribute("disabled")).toBe(false);
  });

  it("promises the weekly digest when that is the only brief", async () => {
    renderField({ frequency: "weekly_only", hour: 8 }, "brief");

    expect(
      await screen.findByText("Results wait for your next weekly digest."),
    ).toBeTruthy();
    expect(
      screen.queryByText("Results wait for your next daily brief."),
    ).toBeNull();
  });

  it("is unavailable, with the reason and the way back, when briefs are off", async () => {
    renderField({ frequency: "off", hour: 8 }, "now");

    expect(
      await screen.findByText(
        "Briefs are off, so there's no brief to add results to.",
      ),
    ).toBeTruthy();
    expect(briefButton().hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByRole("link", { name: "Turn on briefs" }).getAttribute("href"),
    ).toBe("/settings/notifications");
  });

  it("says once why a workflow already set to the brief has nowhere to go", async () => {
    renderField({ frequency: "off", hour: 8 }, "brief");

    expect(
      await screen.findAllByText(
        "Briefs are off, so there's no brief to add results to.",
      ),
    ).toHaveLength(1);
    expect(
      screen.queryByText(WORKFLOW_DELIVERY_COPY.brief.description),
    ).toBeNull();
  });
});
