/** When Sentry's lazy chunk fails to load, the error it was carrying is logged, not lost as an unhandled rejection. */
import { describe, expect, it, vi } from "vitest";

import { reportToSentry } from "@/lib/observability/reportToSentry";

vi.mock("@/lib/observability/sentryClient", () => {
  throw new Error("chunk load failed");
});

describe("reportToSentry", () => {
  it("logs the original error when the Sentry chunk cannot load", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const original = new Error("render failed");

    reportToSentry(original);

    await vi.waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith(
        expect.stringContaining("Sentry failed to load"),
        original,
        expect.anything(),
      ),
    );
  });
});
