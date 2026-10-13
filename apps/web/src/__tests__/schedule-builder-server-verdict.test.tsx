// @vitest-environment jsdom
//
// The server owns the recurring-schedule rule. A cron that looks fine field by
// field but never fires (Feb 31st) must be refused in the form, with the
// server's own reason, rather than only when the workflow is saved.
import type { CronValidationResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ScheduleBuilder } from "@/features/workflows/components/ScheduleBuilder";

const NEVER_FIRES = "That schedule never fires.";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api/typed", () => ({ api: { get: apiGet } }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    {children}
  </QueryClientProvider>
);

describe("ScheduleBuilder custom cron", () => {
  it("shows the server's reason for a schedule that never fires", async () => {
    const verdict: CronValidationResponse = {
      expression: "0 0 31 2 *",
      valid: false,
      error: NEVER_FIRES,
      reason: "never_fires",
    };
    apiGet.mockResolvedValue(verdict);

    // A step hour opens the builder on its custom cron field.
    render(
      <ScheduleBuilder
        value="0 */2 * * *"
        onChange={vi.fn()}
        timezone="UTC"
        onTimezoneChange={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByLabelText("Cron expression"), {
      target: { value: "0 0 31 2 *" },
    });

    expect(await screen.findByText(NEVER_FIRES)).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/reminders/cron/validate", {
      query: { expression: "0 0 31 2 *" },
      silent: true,
    });
  });
});
