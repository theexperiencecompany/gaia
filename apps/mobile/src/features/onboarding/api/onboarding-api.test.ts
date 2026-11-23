import { beforeEach, describe, expect, it, vi } from "vitest";
import { reportOnboardingStep } from "./onboarding-api";

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));

vi.mock("@/lib/api", () => ({ apiService: { post: postMock } }));

describe("reportOnboardingStep", () => {
  beforeEach(() => {
    postMock.mockReset();
  });

  // The tour used to post its own screen names ("welcome", "complete") plus a
  // `completed` flag, which the phase contract rejects with a 422.
  it("posts only the phase the server's contract accepts", async () => {
    postMock.mockResolvedValue({ phase: "started", first_time: true });

    await reportOnboardingStep("started");

    expect(postMock).toHaveBeenCalledExactlyOnceWith("/onboarding/phase", {
      phase: "started",
    });
  });
});
